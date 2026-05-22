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

  // Global pacing — tuned for "comfortable scanning" pace. Lower
  // timeScale = slower animations + pauses. TYPE_SCALE multiplies
  // typing-speed ms/char.
  gsap.globalTimeline.timeScale(0.92);   // was 0.77 — 7-scene loop felt long; slight tightening
  const TYPE_SCALE = 1.15;               // was 1.30 — type a touch faster, still readable

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
    const speed = (opts.speed || 22) * TYPE_SCALE;   // ms per char
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
    sceneLabel.textContent = `Scene ${n} of 7 — ${label}`;
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

  async function sceneDecisionOutcome() {
    setScene(2, 'A decision, revisited');
    clearAll();

    // Initial decision saved with reasoning
    const u1 = addMsg('user', '');
    await gsap.to(u1, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u1, 'Save: bought 100 shares of ABC at £2.10 — Q4 margins expanded, sector hasn\'t rotated yet.', { speed: 18 });

    const t1 = addMsg('tool',
      'pa_add(\n  kind="decision",\n  title="Bought 100 ABC at £2.10",\n  body="Q4 margins expanded, sector rotation lagging…",\n  data={"amount":210,"currency":"GBP","category":"investment"}\n)');
    await gsap.to(t1, { opacity: 1, y: 0, duration: 0.35 });

    const card = addIndexCard({
      id: '#56', kind: 'decision',
      title: 'Bought 100 ABC at £2.10',
      when: 'Today · £210',
      why: '"Q4 margins expanded, sector rotation lagging…"'
    });
    card.style.borderLeftColor = '#7A2E1F';
    await gsap.to(card, { opacity: 1, y: 0, rotate: -0.8, duration: 0.55, ease: 'power2.out' });

    await gsap.to({}, { duration: 1.2 });

    // Time skip — months later, add the outcome
    const sysmsg = addMsg('claude', '<em style="color:var(--graphite)">— 4 months later —</em>');
    await gsap.to(sysmsg, { opacity: 1, y: 0, duration: 0.4 });
    await gsap.to({}, { duration: 0.5 });

    const u2 = addMsg('user', '');
    await gsap.to(u2, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u2, 'ABC played out — sold at £2.85, 35% up. Append the outcome to that decision.', { speed: 18 });

    const t2 = addMsg('tool',
      'pa_update(\n  item_id=56,\n  body="…\\n\\n## Outcome 2026-09-22\\nSold at £2.85, +35%. Thesis on Q4 margins played out as expected."\n)');
    await gsap.to(t2, { opacity: 1, y: 0, duration: 0.35 });

    // Animate an "outcome" line appearing on the existing card
    const outcomeLine = document.createElement('div');
    outcomeLine.className = 'card-why';
    outcomeLine.style.borderTop = '0.5px solid var(--hairline)';
    outcomeLine.style.marginTop = '0.35rem';
    outcomeLine.style.paddingTop = '0.45rem';
    outcomeLine.style.color = '#3F4A3A';
    outcomeLine.style.opacity = '0';
    outcomeLine.textContent = '✓ Outcome (Sep 2026): sold at £2.85, +35%. Thesis held.';
    card.appendChild(outcomeLine);
    await gsap.to(outcomeLine, { opacity: 1, duration: 0.6 });

    // Brief highlight
    await gsap.to(card, { boxShadow: '0 0 0 2px var(--moss), 0 4px 14px rgba(28, 26, 23, 0.12)', duration: 0.35 });
    await gsap.to(card, { boxShadow: '0 4px 14px rgba(28, 26, 23, 0.08)', duration: 0.4 });

    const close = addMsg('claude', 'Outcome appended — your original reasoning stays intact, the result lives below it. Append-only means future-you can compare what-you-thought-then vs what-actually-happened.');
    await gsap.to(close, { opacity: 1, y: 0, duration: 0.4 });

    await gsap.to({}, { duration: 2.6 });
  }

  async function scene2() {
    setScene(3, 'A morning push');
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

  async function sceneTravel() {
    setScene(5, 'Travel intelligence');
    clearAll();

    const u = addMsg('user', '');
    await gsap.to(u, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u, 'I\'m in Tokyo next week — what places have I saved there?', { speed: 20 });
    await gsap.to({}, { duration: 0.4 });

    const tool = addMsg('tool', 'pa_list(\n  kind="place",\n  q="Tokyo",\n  limit=10\n)');
    await gsap.to(tool, { opacity: 1, y: 0, duration: 0.4 });
    await gsap.to({}, { duration: 0.4 });

    const cardSpec = [
      { id: '#67', kind: 'place', title: 'Aoyama Flower Market — Cha-no-ma',
        when: 'Visited Mar 2023 · Tokyo · Aoyama',
        why: '★★★★★ · "the rose-petal tea changed my mind about tea bars"' },
      { id: '#71', kind: 'place', title: 'Butagumi Tonkatsu',
        when: 'Visited Mar 2023 · Tokyo · Roppongi',
        why: '★★★★☆ · "go early, queue forms by 18:00"' },
      { id: '#74', kind: 'place', title: 'Cow Books — Shimokitazawa',
        when: 'Visited Mar 2023 · Tokyo · Setagaya',
        why: '★★★★★ · "small but the curation is perfect, half day disappeared"' },
    ];
    const cards = [];
    for (const spec of cardSpec) {
      const c = addIndexCard(spec);
      c.style.borderLeftColor = '#3F4A3A';
      cards.push(c);
    }
    for (const c of cards) {
      await gsap.to(c, { opacity: 1, y: 0, rotate: gsap.utils.random(-1.2, 1.2), duration: 0.4, ease: 'power2.out' });
    }
    await gsap.to({}, { duration: 0.3 });

    const reply = addMsg('claude', '');
    await gsap.to(reply, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(reply,
      'Three places from your last Tokyo trip — a tea house in Aoyama, a tonkatsu spot in Roppongi, and a bookshop in Shimokitazawa. Want me to add them to your itinerary?',
      { speed: 16 });

    await gsap.to({}, { duration: 2.6 });
  }

  async function sceneMorningBriefing() {
    setScene(4, '"What\'s on my plate today?"');
    clearAll();

    const u = addMsg('user', '');
    await gsap.to(u, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u, 'Good morning — what\'s on my plate today?', { speed: 20 });
    await gsap.to({}, { duration: 0.4 });

    const ack = addMsg('claude', 'Let me check your archive for today.');
    await gsap.to(ack, { opacity: 1, y: 0, duration: 0.4 });

    // Multiple tool calls in sequence
    const t1 = addMsg('tool', 'pa_list(kind="event", due_at="today")');
    await gsap.to(t1, { opacity: 1, y: 0, duration: 0.3 });
    const t2 = addMsg('tool', 'pa_list(kind="todo", due_at="today")');
    await gsap.to(t2, { opacity: 1, y: 0, duration: 0.3 });
    const t3 = addMsg('tool', 'pa_search(q="birthday", due_at="this_week")');
    await gsap.to(t3, { opacity: 1, y: 0, duration: 0.3 });
    const t4 = addMsg('tool', 'pa_list(kind="contract", due_within="30d")');
    await gsap.to(t4, { opacity: 1, y: 0, duration: 0.3 });

    // Cards stagger in across the archive view
    const cards = [
      { id: '#47', kind: 'event', title: 'Dentist — Dr. Sharma',
        when: 'Today · 10:30', why: 'Allow 45 min · SW1' },
      { id: '#42', kind: 'todo', title: 'Pick up Kepei from piano',
        when: 'Today · 16:00', why: 'Push set for 15:45' },
      { id: '#19', kind: 'person', title: 'Mum — birthday today',
        when: '🎂 Today',
        why: 'Last gift: vintage cookbook (3y ago, she loved it)' },
      { id: '#43', kind: 'contract', title: 'IONOS VPS renews in 6 days',
        when: 'May 28 · £12/mo', why: 'Decision: keep XL+ or downsize?' },
    ];
    for (const spec of cards) {
      const c = addIndexCard(spec);
      await gsap.to(c, { opacity: 1, y: 0, rotate: 0, duration: 0.4, ease: 'power2.out' });
    }
    await gsap.to({}, { duration: 0.3 });

    const reply = addMsg('claude', '');
    await gsap.to(reply, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(reply,
      'Here\'s your day:\n\n📅 Dentist 10:30 · pick up Kepei 16:00\n🎂 It\'s Mum\'s birthday today — last gift was a cookbook she loved\n⚠️ IONOS VPS renews in 6 days, worth deciding if you still need the XL+ tier\n\nWant me to draft a birthday message, or queue any of these as todos?',
      { speed: 14 });

    await gsap.to({}, { duration: 3.2 });
  }

  async function sceneCrossMcp() {
    setScene(6, 'When another MCP leaves a mark');
    clearAll();

    // 5.1 — User asks Claude to book a hotel via another MCP
    const u1 = addMsg('user', '');
    await gsap.to(u1, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u1, 'Book a hotel in Tokyo for 14–18 March — Shibuya area, under £200/night.', { speed: 18 });

    const ack = addMsg('claude', 'Checking Hotels.com…');
    await gsap.to(ack, { opacity: 1, y: 0, duration: 0.35 });

    // hotels_com tool call — visually distinct from pa_* calls
    const hcSearch = addMsg('tool-other',
      'hotels_com.search(\n  location="Shibuya, Tokyo",\n  check_in="2027-03-14",\n  check_out="2027-03-18",\n  max_nightly=200, currency="GBP"\n)');
    await gsap.to(hcSearch, { opacity: 1, y: 0, duration: 0.35 });

    const hcBook = addMsg('tool-other',
      'hotels_com.book(\n  property_id="HC-89421",\n  guest="Kenny", nights=4\n)\n→ booked · ref HC-89421');
    await gsap.to(hcBook, { opacity: 1, y: 0, duration: 0.35 });

    const claudeBooked = addMsg('claude', 'Booked — Trunk(Hotel) Yoyogi-Uehara, £178/night, ref HC-89421. I\'ll log it to MyPA so it\'s there next time you ask.');
    await gsap.to(claudeBooked, { opacity: 1, y: 0, duration: 0.4 });

    // 5.2 — MyPA captures the durable fact from the cross-MCP transaction
    const paAdd = addMsg('tool',
      'pa_add(\n  kind="trip",\n  title="Tokyo · Shibuya · Mar 2027",\n  data={\n    "hotel":"Trunk(Hotel) Yoyogi-Uehara",\n    "nights":4, "nightly":178, "currency":"GBP",\n    "booking_ref":"HC-89421", "source":"hotels.com"\n  }\n)');
    await gsap.to(paAdd, { opacity: 1, y: 0, duration: 0.35 });

    const card = addIndexCard({
      id: '#84', kind: 'trip',
      title: 'Tokyo · Shibuya · Mar 2027',
      when: '14–18 March · 4 nights',
      why: 'Trunk(Hotel) Yoyogi-Uehara · £178/night · booked via Hotels.com'
    });
    card.style.borderLeftColor = '#3F4A3A';
    await gsap.to(card, { opacity: 1, y: 0, rotate: -1, duration: 0.55, ease: 'power2.out' });

    await gsap.to({}, { duration: 1.4 });

    // 5.3 — Time skip; user asks later
    const sysmsg = addMsg('claude', '<em style="color:var(--graphite)">— 8 months later · planning next Tokyo trip —</em>');
    await gsap.to(sysmsg, { opacity: 1, y: 0, duration: 0.4 });
    await gsap.to({}, { duration: 0.5 });

    const u2 = addMsg('user', '');
    await gsap.to(u2, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(u2, 'Where did I stay in Tokyo back in March?', { speed: 22 });

    const paSearch = addMsg('tool', 'pa_search(q="Tokyo March", kind="trip")');
    await gsap.to(paSearch, { opacity: 1, y: 0, duration: 0.35 });

    // Card glows
    await gsap.to(card, { boxShadow: '0 0 0 2px var(--oxblood), 0 4px 14px rgba(28, 26, 23, 0.12)', duration: 0.35 });
    await gsap.to(card, { boxShadow: '0 4px 14px rgba(28, 26, 23, 0.08)', duration: 0.4 });

    const reply = addMsg('claude', '');
    await gsap.to(reply, { opacity: 1, y: 0, duration: 0.3 });
    await typeInto(reply,
      'Trunk(Hotel) Yoyogi-Uehara in Shibuya — 4 nights, 14–18 March, £178/night, booked via Hotels.com (ref HC-89421). Want me to check availability for similar dates this year?',
      { speed: 16 });

    await gsap.to({}, { duration: 2.6 });
  }

  async function scene3() {
    setScene(7, 'Recall, across kinds');
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
        await sceneDecisionOutcome();
        if (ac.aborted) break;
        await scene2();
        if (ac.aborted) break;
        await sceneMorningBriefing();
        if (ac.aborted) break;
        await sceneTravel();
        if (ac.aborted) break;
        await sceneCrossMcp();
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

  // Allow click-to-skip on the scene label — jump forward (rough but useful)
  const sceneLabelEl = document.getElementById('demo-scene-label');
  if (sceneLabelEl) {
    sceneLabelEl.style.cursor = 'pointer';
    sceneLabelEl.title = 'click to skip ahead';
    sceneLabelEl.addEventListener('click', () => {
      stopLoop();
      setTimeout(runLoop, 100);   // restart loop; loop is short enough that this is a reasonable "next"
    });
  }

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
