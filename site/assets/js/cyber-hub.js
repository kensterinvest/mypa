/* ============================================================
 * cyber-hub.js — animates the hero's connection-graph SVG.
 *
 * Pulses travel along link paths between MyPA (centre) and each
 * satellite node (claude, mcp, ntfy, calendar, dashboard, telegram).
 * Inbound pulses use steel-cyan; outbound pulses use mint.
 *
 * Requires gsap + MotionPathPlugin (both loaded in index.html).
 * Respects prefers-reduced-motion.
 * ============================================================ */

(function initCyberHub() {
  if (typeof gsap === 'undefined') return;
  const svg = document.querySelector('.cyber-hub-svg');
  if (!svg) return;

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  if (gsap.registerPlugin && window.MotionPathPlugin) {
    gsap.registerPlugin(window.MotionPathPlugin);
  }

  const pulses = svg.querySelectorAll('.pulse');
  pulses.forEach((dot, i) => {
    const pathSel = dot.getAttribute('data-path');
    const path = svg.querySelector(pathSel);
    if (!path) return;
    const isInbound = dot.classList.contains('pulse-in');

    gsap.timeline({ repeat: -1, delay: i * 0.45 })
      .set(dot, { opacity: 0 })
      .to(dot, {
        duration: 2.6,
        ease: 'power1.inOut',
        motionPath: {
          path: path,
          align: path,
          alignOrigin: [0.5, 0.5],
          start: isInbound ? 1 : 0,
          end:   isInbound ? 0 : 1,
        },
        keyframes: [
          { opacity: 0,   duration: 0.05 },
          { opacity: 1,   duration: 0.25 },
          { opacity: 1,   duration: 2.0  },
          { opacity: 0,   duration: 0.30 },
        ],
      })
      .to({}, { duration: 1.2 });
  });
})();
