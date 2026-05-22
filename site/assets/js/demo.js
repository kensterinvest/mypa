/* ============================================================
 * MyPA demo — three scenes of Claude working with the archive.
 * Real GSAP-driven DOM animation. No static-image trickery.
 *
 * Scene 1 — Save a decision (chat → tool call → index card files itself)
 * Scene 2 — Morning push lands (push toast slides in, card "glows")
 * Scene 3 — Recall the decision (chat search → card flies into reply)
 * ============================================================ */

(function () {
  'use strict';

  if (typeof gsap === 'undefined') {
    console.warn('GSAP not loaded — demo will not animate.');
    return;
  }

  // -- DOM refs ----------------------------------------------------------
  const chatBody = document.getElementById('chat-body');
  const storeBody = document.getElementById('store-body');
  const sceneLabel = document.getElementById('demo-scene-label');
  const playBtn = document.getElementById('demo-play');
  const pauseBtn = document.getElementById('demo-pause');
  const restartBtn = document.getElementById('demo-restart');
  const pushEl = document.getElementById('demo-push');
  const pushTitle = document.getElementById('push-title');
  const pushBody = document.getElementById('push-body');

  if (!chatBody || !storeBody) return;

  // -- Helpers -----------------------------------------------------------

  /** Append a chat message; returns the element (hidden, animated in by GSAP). */
  function addMsg(role, html) {
    const el = document.createElement('div');
    el.className = 'chat-msg ' + role;
    el.innerHTML = html;
    chatBody.appendChild(el);
    return el;
  }

  /** Type text into an element char-by-char. */
  function typeInto(el, text, opts = {}) {
    const speed = opts.speed || 22;   // ms per char
    return new Promise((resolve) => {
      let i = 0;
      el.innerHTML = '<span class="chat-cursor"></span>';
      const cursor = el.querySelector('.chat-cursor');
      const tick = setInterval(() => {
        if (i >= text.length) {
          clearInterval(tick);
          cursor.remove();
          resolve();
          return;
        }
        cursor.insertAdjacentText('beforebegin', text.charAt(i));
        i++;
      }, speed);
    });
  }

  function addIndexCard({ id, kind, title, when, why }) {
    // Remove the "empty" placeholder if present
    const empty = storeBody.querySelector('.store-empty');
    if (empty) empty.remove();
    const card = document.createElement('div');
    card.className = 'index-card';
    card.innerHTML = `
      <div><span class="card-id">${id}</span><span class="card-kind">${kind}</span></div>
      <div class="card-title">${title}</div>
      <div class="card-meta">${when}</div>
      ${why ? `<div class="card-why">${why}</div>` : ''}
    `;
    storeBody.appendChild(card);
    return card;
  }

  function clearAll() {
    chatBody.innerHTML = '';
    storeBody.innerHTML = '<div class="store-empty">— no items saved yet —</div>';
    pushEl.style.opacity = 0;
    pushEl.style.transform = 'translateY(-30px) scale(0.95)';
  }

  function setScene(n, label) {
    sceneLabel.textContent = `Scene ${n} of 3 — ${label}`;
  }

  // -- Scenes ------------------------------------------------------------

  async function scene1() {
    setScene(1, 'Save a decision');
    clearAll();

    // 1.1 User types
    const userMsg = addMsg('user', '');
    await gsap.to(userMsg, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(userMsg,
      'Save: bought 100 shares of ABC at £2.10. I think it\'s undervalued — Q4 margins expanded, sector rotation hasn\'t caught up yet.',
      { speed: 18 });

    await gsap.to({}, { duration: 0.6 });   // pause

    // 1.2 Claude acknowledges
    const claudeAck = addMsg('claude', 'Saving as a decision — capturing your reasoning so you can come back to it later.');
    await gsap.to(claudeAck, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 0.4 });

    // 1.3 Tool call card
    const toolCall = addMsg('tool',
      'pa_add(\n' +
      '  kind="decision",\n' +
      '  title="Bought 100 ABC at £2.10",\n' +
      '  data={"category":"investment","amount":210,"currency":"GBP"},\n' +
      '  body="Q4 margins expanded, sector rotation lagging…"\n' +
      ')');
    await gsap.to(toolCall, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 0.5 });

    // 1.4 Index card materialises in the store
    const card = addIndexCard({
      id: '#42',
      kind: 'decision',
      title: 'Bought 100 ABC at £2.10',
      when: 'Today · 14:22 GMT',
      why: '"Q4 margins expanded, sector rotation lagging…"'
    });
    await gsap.to(card, { opacity: 1, y: 0, rotate: -1, duration: 0.7, ease: 'power2.out' });

    // 1.5 Claude closes the loop
    const claudeDone = addMsg('claude', 'Saved as decision #42. I\'ve preserved the reasoning verbatim — append-only, so future-you can read past-you\'s thinking.');
    await gsap.to(claudeDone, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 2.5 });
  }

  async function scene2() {
    setScene(2, 'A morning reminder');
    clearAll();

    // Bring back the card from scene 1 (slightly different time)
    const card = addIndexCard({
      id: '#42',
      kind: 'decision',
      title: 'Bought 100 ABC at £2.10',
      when: 'Yesterday',
      why: '"Q4 margins expanded, sector rotation lagging…"'
    });
    gsap.set(card, { opacity: 1, y: 0, rotate: -1 });

    // System time-skip cue in chat
    const systemMsg = addMsg('claude', '<em style="color:var(--graphite)">— next morning · 07:00 London —</em>');
    await gsap.to(systemMsg, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 0.5 });

    // Push notification slides down from top
    pushTitle.textContent = 'MyPA — Friday 22 May';
    pushBody.textContent = '1 reminder due today · daily digest · 2 todos due';
    await gsap.fromTo(pushEl,
      { opacity: 0, y: -40, scale: 0.92 },
      { opacity: 1, y: 0, scale: 1, duration: 0.55, ease: 'power3.out' });

    // Card glows oxblood briefly
    await gsap.to(card, {
      boxShadow: '0 0 0 2px var(--oxblood), 0 4px 14px rgba(28, 26, 23, 0.12)',
      duration: 0.5
    });
    await gsap.to(card, {
      boxShadow: '0 4px 14px rgba(28, 26, 23, 0.08)',
      duration: 0.7
    });

    await gsap.to({}, { duration: 1.5 });

    // Push lingers, then slides up and out
    await gsap.to(pushEl, { opacity: 0, y: -30, scale: 0.95, duration: 0.4 });

    await gsap.to({}, { duration: 1.4 });
  }

  async function scene3() {
    setScene(3, 'Recall, months later');
    clearAll();

    // The card persists in the archive (was saved months ago)
    const card = addIndexCard({
      id: '#42',
      kind: 'decision',
      title: 'Bought 100 ABC at £2.10',
      when: '4 months ago',
      why: '"Q4 margins expanded, sector rotation lagging…"'
    });
    gsap.set(card, { opacity: 1, y: 0, rotate: -1 });

    // User asks Claude
    const userMsg = addMsg('user', '');
    await gsap.to(userMsg, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(userMsg, 'Why did I buy ABC again? I want to check if my thesis still holds.', { speed: 22 });

    await gsap.to({}, { duration: 0.5 });

    // Tool call — search
    const toolCall = addMsg('tool', 'pa_search(q="ABC", limit=5)');
    await gsap.to(toolCall, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 0.5 });

    // Card visually pulses (search hit)
    await gsap.to(card, { scale: 1.04, duration: 0.25, ease: 'power2.out' });
    await gsap.to(card, { scale: 1, duration: 0.35 });

    // Claude streams back the recall
    const claudeReply = addMsg('claude', '');
    await gsap.to(claudeReply, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(claudeReply,
      'Found it — decision #42, recorded 4 months ago. Your reasoning at the time: "Q4 margins expanded, sector rotation lagging." Want me to check whether that thesis has played out?',
      { speed: 18 });

    await gsap.to({}, { duration: 3 });
  }

  // -- Runner ------------------------------------------------------------

  let isPlaying = false;
  let abortController = null;

  async function runLoop() {
    if (isPlaying) return;
    isPlaying = true;
    abortController = { aborted: false };
    const ac = abortController;
    while (!ac.aborted) {
      try {
        await scene1();
        if (ac.aborted) break;
        await scene2();
        if (ac.aborted) break;
        await scene3();
      } catch (e) { /* swallow */ break; }
    }
    isPlaying = false;
  }

  function stopLoop() {
    if (abortController) abortController.aborted = true;
    isPlaying = false;
  }

  // -- Controls ----------------------------------------------------------

  playBtn?.addEventListener('click', () => { if (!isPlaying) runLoop(); });
  pauseBtn?.addEventListener('click', () => { stopLoop(); });
  restartBtn?.addEventListener('click', () => { stopLoop(); setTimeout(runLoop, 100); });

  // -- Auto-start when demo enters viewport ------------------------------

  const stage = document.querySelector('.demo-stage');
  if (stage && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !isPlaying) runLoop();
        else if (!e.isIntersecting && isPlaying) {
          // Don't stop when scrolling away — just let it loop quietly.
          // Browser will throttle anyway.
        }
      });
    }, { threshold: 0.25 });
    io.observe(stage);
  } else {
    // Fallback: just start.
    setTimeout(runLoop, 800);
  }

})();
