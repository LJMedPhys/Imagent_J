// Agentic-J landing — small, dependency-free progressive enhancement.

// 1) Reveal-on-scroll
const io = new IntersectionObserver((entries) => {
  entries.forEach((e) => {
    if (e.isIntersecting) {
      e.target.classList.add('in');
      io.unobserve(e.target);
    }
  });
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.reveal').forEach((el) => io.observe(el));

// 2) Copy-code buttons
document.querySelectorAll('.code [data-copy]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const pre = btn.closest('.code');
    if (!pre) return;
    const text = Array.from(pre.childNodes)
      .filter((n) => n !== btn)
      .map((n) => n.textContent || '')
      .join('')
      .trim();
    try {
      await navigator.clipboard.writeText(text);
      const old = btn.textContent;
      btn.textContent = 'copied ✓';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = old; btn.classList.remove('copied'); }, 1500);
    } catch {
      btn.textContent = 'select & copy';
    }
  });
});

// 3) Active nav link as you scroll
const sections = ['overview', 'install', 'demos', 'reproducibility', 'docs', 'paper']
  .map((id) => document.getElementById(id))
  .filter(Boolean);
const navLinks = new Map(
  Array.from(document.querySelectorAll('.nav-links a'))
    .filter((a) => a.getAttribute('href')?.startsWith('#'))
    .map((a) => [a.getAttribute('href').slice(1), a])
);
const navIO = new IntersectionObserver((entries) => {
  entries.forEach((e) => {
    if (!e.isIntersecting) return;
    navLinks.forEach((a) => a.classList.remove('active'));
    const link = navLinks.get(e.target.id);
    if (link) link.classList.add('active');
  });
}, { rootMargin: '-45% 0px -45% 0px' });
sections.forEach((s) => navIO.observe(s));

// 4) YouTube slots: set data-youtube="<video id>" on a .video element to embed it
document.querySelectorAll('.video[data-youtube]').forEach((slot) => {
  const id = slot.dataset.youtube.trim();
  if (!id) return;
  const f = document.createElement('iframe');
  f.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?rel=0`;
  f.title = slot.dataset.title || 'Agentic-J video';
  f.loading = 'lazy';
  f.allow = 'accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen';
  f.allowFullscreen = true;
  f.referrerPolicy = 'strict-origin-when-cross-origin';
  slot.classList.remove('empty');
  slot.replaceChildren(f);
  // Fallback link in case the embed is blocked (extensions, embedding disabled, ...)
  const a = document.createElement('a');
  a.className = 'yt-link';
  a.href = `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = 'Watch on YouTube ↗';
  slot.closest('.window').after(a);
});

// 5) Demo tabs
const tabs = Array.from(document.querySelectorAll('.tabs [role="tab"]'));
function selectTab(tab) {
  tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
  });
}
tabs.forEach((tab, i) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', (e) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    const next = tabs[(i + step + tabs.length) % tabs.length];
    selectTab(next);
    next.focus();
  });
});
