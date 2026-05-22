/* ============================================================
 * MyPA demo — three scenes showing breadth of personal-life data.
 * Real GSAP-driven DOM animation. No static-image trickery.
 *
 * Scene 1 — Capture variety. Three rapid saves across kinds:
 *           a place visited, a recurring family todo, a contract.
 * Scene 2 — A morning digest push aggregating across kinds.
 * Scene 3 — Cross-kind recall: "what about Kepei?" returns todo
 *           + preference + decision + place together.
 *
 * All demo content is hardcoded literals — no user input flows
 * into innerHTML, so no XSS surface.
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
    setScene(1, 'Captured across a week');
    clearAll();

    // 1.1 — a place you visited
    const u1 = addMsg('user', '');
    await gsap.to(u1, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u1, 'Pizza Express on King\'s Road last night — 5 stars, save that.', { speed: 18 });

    const t1 = addMsg('tool',
      'pa_add(\n  kind="place",\n  title="Pizza Express, King\'s Road",\n  data={"rating":5,"visited_at":"yesterday"}\n)');
    await gsap.to(t1, { opacity: 1, y: 0, duration: 0.35 });

    const card1 = addIndexCard({
      id: '#41', kind: 'place',
      title: 'Pizza Express, King\'s Road',
      when: 'Yesterday · London SW',
      why: '★★★★★ · "burrata was a surprise"'
    });
    card1.style.borderLeftColor = '#3F4A3A';
    await gsap.to(card1, { opacity: 1, y: 0, rotate: -1, duration: 0.55, ease: 'power2.out' });
    await gsap.to({}, { duration: 0.55 });

    // 1.2 — a recurring family todo
    const u2 = addMsg('user', '');
    await gsap.to(u2, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u2, 'Kepei has piano Thursdays at 4pm — remind me to pick her up.', { speed: 18 });

    const t2 = addMsg('tool',
      'pa_add(\n  kind="todo",\n  title="Pick up Kepei from piano",\n  data={"recurring":"Thu 16:00"}\n)\npa_add_reminder(item_id=42, fire_at="Thu 15:45")');
    await gsap.to(t2, { opacity: 1, y: 0, duration: 0.35 });

    const card2 = addIndexCard({
      id: '#42', kind: 'todo',
      title: 'Pick up Kepei from piano',
      when: 'Recurring · Thursdays 16:00',
      why: 'Reminder set · push 15 min before'
    });
    card2.style.borderLeftColor = '#7A2E1F';
    await gsap.to(card2, { opacity: 1, y: 0, rotate: -0.5, duration: 0.55, ease: 'power2.out' });
    await gsap.to({}, { duration: 0.55 });

    // 1.3 — a durable contract / life-admin fact
    const u3 = addMsg('user', '');
    await gsap.to(u3, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u3, 'My IONOS VPS contract ends May 2027 — log it.', { speed: 18 });

    const t3 = addMsg('tool',
      'pa_add(\n  kind="contract",\n  title="IONOS VPS Linux XL+",\n  data={"end":"2027-05","monthly":12,"currency":"GBP"}\n)');
    await gsap.to(t3, { opacity: 1, y: 0, duration: 0.35 });

    const card3 = addIndexCard({
      id: '#43', kind: 'contract',
      title: 'IONOS VPS Linux XL+',
      when: 'Ends May 2027 · 13 months out',
      why: '£12/mo · will alert 30 days before renewal'
    });
    card3.style.borderLeftColor = '#8B8275';
    await gsap.to(card3, { opacity: 1, y: 0, rotate: -1.2, duration: 0.55, ease: 'power2.out' });
    await gsap.to({}, { duration: 0.4 });

    const close = addMsg('claude', 'All three saved. Your archive now spans places visited, family logistics, and durable life facts — all queryable in one search.');
    await gsap.to(close, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 2.6 });
  }

  async function scene2() {
    setScene(2, 'A morning, gathered');
    clearAll();

    // Items already in the archive — today's relevant slice
    const c1 = addIndexCard({
      id: '#47', kind: 'event',
      title: 'Dentist — Dr. Sharma',
      when: 'Today · 10:30',
      why: 'Allow 45 min · postcode SW1'
    });
    c1.style.borderLeftColor = '#3F4A3A';
    const c2 = addIndexCard({
      id: '#42', kind: 'todo',
      title: 'Pick up Kepei from piano',
      when: 'Today · 16:00',
      why: 'Reminder will fire at 15:45'
    });
    c2.style.borderLeftColor = '#7A2E1F';
    const c3 = addIndexCard({
      id: '#43', kind: 'contract',
      title: 'IONOS VPS renews next month',
      when: 'Heads-up · 30 days',
      why: '£12/mo — review if XL+ tier still needed'
    });
    c3.style.borderLeftColor = '#8B8275';
    gsap.set([c1, c2, c3], { opacity: 1, y: 0, rotate: -0.8 });

    const sysmsg = addMsg('claude', '<em style="color:var(--graphite)">— Friday morning · 07:00 London —</em>');
    await gsap.to(sysmsg, { opacity: 1, y: 0, duration: 0.4 });
    await gsap.to({}, { duration: 0.5 });

    pushTitle.textContent = 'MyPA — Friday';
    // Push body has formatted hardcoded content — keep DOM-safe via textContent + spans
    pushBody.textContent = '';
    const b1 = document.createElement('strong'); b1.textContent = 'Today: '; pushBody.appendChild(b1);
    pushBody.appendChild(document.createTextNode('dentist 10:30 · pick up Kepei 16:00'));
    pushBody.appendChild(document.createElement('br'));
    const b2 = document.createElement('strong'); b2.textContent = 'Heads-up: '; pushBody.appendChild(b2);
    pushBody.appendChild(document.createTextNode('IONOS renews in 30 days'));

    await gsap.fromTo(pushEl,
      { opacity: 0, y: -40, scale: 0.92 },
      { opacity: 1, y: 0, scale: 1, duration: 0.55, ease: 'power3.out' });

    // Each relevant card glows briefly to show the cross-kind tie
    await gsap.to(c1, { boxShadow: '0 0 0 2px var(--oxblood), 0 4px 14px rgba(28, 26, 23, 0.12)', duration: 0.35 });
    await gsap.to(c1, { boxShadow: '0 4px 14px rgba(28, 26, 23, 0.08)', duration: 0.4 });
    await gsap.to(c2, { boxShadow: '0 0 0 2px var(--oxblood), 0 4px 14px rgba(28, 26, 23, 0.12)', duration: 0.35 });
    await gsap.to(c2, { boxShadow: '0 4px 14px rgba(28, 26, 23, 0.08)', duration: 0.4 });
    await gsap.to(c3, { boxShadow: '0 0 0 2px var(--moss), 0 4px 14px rgba(28, 26, 23, 0.12)', duration: 0.35 });
    await gsap.to(c3, { boxShadow: '0 4px 14px rgba(28, 26, 23, 0.08)', duration: 0.4 });

    await gsap.to({}, { duration: 1.5 });
    await gsap.to(pushEl, { opacity: 0, y: -30, scale: 0.95, duration: 0.4 });
    await gsap.to({}, { duration: 1.4 });
  }

  async function scene3() {
    setScene(3, 'Recall, across kinds');
    clearAll();

    const user = addMsg('user', '');
    await gsap.to(user, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(user, 'What have I saved about Kepei?', { speed: 22 });
    await gsap.to({}, { duration: 0.4 });

    const tool = addMsg('tool', 'pa_search(q="Kepei", limit=10)');
    await gsap.to(tool, { opacity: 1, y: 0, duration: 0.4 });
    await gsap.to({}, { duration: 0.4 });

    const cardSpec = [
      { id: '#42', kind: 'todo', title: 'Pick up Kepei from piano',
        when: 'Recurring · Thursdays 16:00',
        why: 'Last fired: yesterday · 15 min ahead push', accent: '#7A2E1F' },
      { id: '#28', kind: 'preference', title: 'Kepei loves dinosaurs',
        when: 'Saved 3 months ago',
        why: 'context: birthday-gift ideas, museums, books', accent: '#3F4A3A' },
      { id: '#15', kind: 'decision', title: 'Switched Kepei to morning piano slot',
        when: '6 months ago',
        why: '"afternoon clash with swim — Tuesday evening didn\'t stick"', accent: '#7A2E1F' },
      { id: '#39', kind: 'place', title: 'Hummingbird Bakery — Kepei\'s favourite',
        when: 'Visited 2 weeks ago',
        why: '★★★★★ · "the cupcake made her day"', accent: '#3F4A3A' },
    ];
    const cards = [];
    for (const spec of cardSpec) {
      const c = addIndexCard(spec);
      c.style.borderLeftColor = spec.accent;
      cards.push(c);
    }
    for (const c of cards) {
      await gsap.to(c, {
        opacity: 1, y: 0,
        rotate: gsap.utils.random(-1.5, 1.5),
        duration: 0.4, ease: 'power2.out',
      });
    }
    await gsap.to({}, { duration: 0.3 });

    const reply = addMsg('claude', '');
    await gsap.to(reply, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(reply,
      'Four items across four kinds — a recurring todo, a preference (useful for gifts), an old scheduling decision, and a place she loves. The whole context of one person, in one query.',
      { speed: 16 });

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
