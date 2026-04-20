/* ═══════════════════════════════════════════════════════════
   script.js — @vgbuy shop
   - Canvas particles
   - Scroll reveal (IntersectionObserver)
   - Animated counters
   - Button ripple (mouse + touch)
   - Header scroll state
   - Smooth parallax on hero grid
════════════════════════════════════════════════════════════ */
'use strict';

(function () {

  // ─── Util ───────────────────────────────────────────
  const qs  = (s, ctx = document) => ctx.querySelector(s);
  const qsa = (s, ctx = document) => [...ctx.querySelectorAll(s)];
  const isMobile = () => window.innerWidth < 600;
  const isTouch  = () => window.matchMedia('(pointer: coarse)').matches;

  // ─── Header scroll state ────────────────────────────
  const header = qs('#siteHeader');
  let lastScroll = 0;

  window.addEventListener('scroll', () => {
    const y = window.scrollY;
    header.classList.toggle('scrolled', y > 20);
    lastScroll = y;
  }, { passive: true });


  // ─── Canvas particles ───────────────────────────────
  (function initParticles() {
    const canvas = qs('#particleCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let W, H, particles = [];

    const COUNT = isTouch() ? 30 : 55;
    const ORANGE = [255, 144, 0];

    function resize() {
      W = canvas.width  = canvas.offsetWidth;
      H = canvas.height = canvas.offsetHeight;
    }

    function createParticle() {
      return {
        x:     Math.random() * W,
        y:     Math.random() * H,
        r:     Math.random() * 1.5 + 0.4,
        vx:    (Math.random() - 0.5) * 0.25,
        vy:   -(Math.random() * 0.35 + 0.1),
        alpha: Math.random() * 0.5 + 0.1,
        life:  Math.random() * 200 + 80,
        age:   0,
      };
    }

    function init() {
      resize();
      particles = Array.from({ length: COUNT }, createParticle);
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.age++;

        const progress = p.age / p.life;
        const fade = progress < 0.15
          ? progress / 0.15
          : progress > 0.75
            ? 1 - (progress - 0.75) / 0.25
            : 1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${ORANGE[0]},${ORANGE[1]},${ORANGE[2]},${p.alpha * fade})`;
        ctx.fill();

        if (p.age >= p.life || p.y < -10) {
          particles[i] = createParticle();
          particles[i].y = H + 5;
        }
      }
      requestAnimationFrame(draw);
    }

    window.addEventListener('resize', resize, { passive: true });
    init();
    draw();
  })();


  // ─── Scroll reveal ──────────────────────────────────
  (function initReveal() {
    const els = qsa('.reveal');
    if (!els.length) return;

    const obs = new IntersectionObserver((entries) => {
      entries.forEach((entry, idx) => {
        if (entry.isIntersecting) {
          // stagger within a burst
          const delay = Math.min(idx * 60, 300);
          setTimeout(() => {
            entry.target.classList.add('is-visible');
          }, delay);
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    els.forEach(el => obs.observe(el));
  })();


  // ─── Animated counters ──────────────────────────────
  (function initCounters() {
    const vals = qsa('.stat-val[data-target]');
    const statics = qsa('.stat-val[data-static]');

    // static values
    statics.forEach(el => {
      el.textContent = el.dataset.static;
    });

    if (!vals.length) return;

    const DURATION = 1600;
    const easeOutQuart = t => 1 - Math.pow(1 - t, 4);
    let started = false;

    function animateCounters() {
      const start = performance.now();
      vals.forEach(el => {
        const target = parseInt(el.dataset.target, 10);
        function step(now) {
          const t = Math.min((now - start) / DURATION, 1);
          const val = Math.round(easeOutQuart(t) * target);
          el.textContent = val >= 1000
            ? (val / 1000).toFixed(val % 1000 === 0 ? 0 : 1) + 'K'
            : val;
          if (t < 1) requestAnimationFrame(step);
          else el.textContent = target >= 1000
            ? (target / 1000) + 'K'
            : target;
        }
        requestAnimationFrame(step);
      });
    }

    // Trigger when stats strip enters viewport
    const strip = qs('.stats-strip');
    if (!strip) return;

    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !started) {
        started = true;
        animateCounters();
        obs.disconnect();
      }
    }, { threshold: 0.5 });

    obs.observe(strip);
  })();


  // ─── Button ripple ──────────────────────────────────
  (function initRipple() {
    function spawnRipple(btn, x, y) {
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height) * 2;
      const el = document.createElement('span');
      el.className = 'ripple';
      el.style.cssText = `
        width: ${size}px;
        height: ${size}px;
        left: ${x - rect.left - size / 2}px;
        top: ${y - rect.top - size / 2}px;
      `;
      btn.appendChild(el);
      el.addEventListener('animationend', () => el.remove());
    }

    document.addEventListener('click', e => {
      const btn = e.target.closest('.btn');
      if (!btn) return;
      spawnRipple(btn, e.clientX, e.clientY);
    });

    document.addEventListener('touchstart', e => {
      const btn = e.target.closest('.btn');
      if (!btn || !e.touches[0]) return;
      spawnRipple(btn, e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });
  })();


  // ─── Hero parallax (desktop only) ───────────────────
  (function initParallax() {
    if (isTouch()) return;
    const grid = qs('.hero-grid');
    const glow = qs('.hero-glow');
    if (!grid || !glow) return;

    let ticking = false;

    window.addEventListener('scroll', () => {
      if (ticking) return;
      requestAnimationFrame(() => {
        const y = window.scrollY;
        grid.style.transform = `translateY(${y * 0.18}px)`;
        glow.style.transform = `translate(-50%, calc(-55% + ${y * 0.06}px))`;
        ticking = false;
      });
      ticking = true;
    }, { passive: true });
  })();


  // ─── Smooth anchor scroll ───────────────────────────
  (function initAnchors() {
    document.addEventListener('click', e => {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      const id = a.getAttribute('href').slice(1);
      const target = qs('#' + id);
      if (!target) return;
      e.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - 70;
      window.scrollTo({ top, behavior: 'smooth' });
    });
  })();


  // ─── Card hover tilt (desktop) ──────────────────────
  (function initTilt() {
    if (isTouch()) return;
    qsa('.card').forEach(card => {
      card.addEventListener('mousemove', e => {
        const r = card.getBoundingClientRect();
        const x = ((e.clientX - r.left) / r.width  - 0.5) * 7;
        const y = ((e.clientY - r.top)  / r.height - 0.5) * 7;
        card.style.transform = `perspective(600px) rotateX(${-y}deg) rotateY(${x}deg) translateY(-3px)`;
      });
      card.addEventListener('mouseleave', () => {
        card.style.transform = '';
      });
    });
  })();


  // ─── Stats hover cursor glow (desktop) ──────────────
  (function initStatGlow() {
    if (isTouch()) return;
    qsa('.stat').forEach(stat => {
      stat.addEventListener('mouseenter', () => {
        stat.querySelector('.stat-val').style.textShadow = '0 0 20px rgba(255,144,0,0.7)';
      });
      stat.addEventListener('mouseleave', () => {
        stat.querySelector('.stat-val').style.textShadow = '';
      });
    });
  })();

})();
