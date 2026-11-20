/* Four-workspace router with legacy-hash aliases. Views register before bootstrap. */
const workspaceRoutes = {
  daily: 'daily',
  announcements: 'daily',
  briefing: 'daily',
  method: 'daily',
  recommendations: 'recommendations',
  portfolio: 'portfolio',
  fit: 'portfolio',
  activity: 'portfolio',
  validation: 'validation',
};
const workspaceTitles = {
  daily: 'Overview',
  recommendations: 'Research',
  portfolio: 'Portfolio',
  validation: 'Strategy lab',
};
function workspaceElement(id) {
  if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) return null;
  return document.getElementById ? document.getElementById(id) : $('#' + id);
}
let lastWorkspaceLocation = location.pathname + location.search + location.hash;
function workspaceFromLocation() {
  const hashTarget = location.hash ? location.hash.slice(1) : '';
  return hashTarget && (workspaceRoutes[hashTarget] || workspaceElement(hashTarget))
    ? hashTarget
    : location.pathname === '/recommendations'
    ? 'recommendations'
    : 'daily';
}
function openWorkspace(target, updateHistory = true) {
  const destination = workspaceElement(target);
  const section = destination && destination.closest ? destination.closest('.tab') : null;
  const page = workspaceRoutes[target] || (section && section.id) || 'daily';
  if (!destination) target = page;
  $('#workspaceTitle').textContent = workspaceTitles[page];
  for (const section of document.querySelectorAll('.tab')) section.hidden = section.id !== page;
  for (const button of document.querySelectorAll('[data-tab]')) {
    const active = button.dataset.tab === page;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (target !== page && destination) {
    const group = workspaceElement(target + 'Group');
    if (group) group.open = true;
    for (let node = destination; node; node = node.parentElement)
      if (node.tagName === 'DETAILS') node.open = true;
    if (destination.scrollIntoView)
      destination.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (destination.focus) {
      if (!destination.hasAttribute('tabindex')) destination.setAttribute('tabindex', '-1');
      destination.focus({ preventScroll: true });
    }
  }
  if (updateHistory && typeof history !== 'undefined' && history.pushState) {
    const nextUrl = location.pathname + location.search + '#' + target;
    if (location.pathname + location.search + location.hash !== nextUrl)
      history.pushState({ workspace: target }, '', nextUrl);
    lastWorkspaceLocation = nextUrl;
  }
  if (page === 'daily') {
    if (typeof loadDaily === 'function') loadDaily();
    if (typeof loadSystemStatus === 'function') loadSystemStatus();
  }
  if (page === 'portfolio') {
    if (typeof loadDaily === 'function') loadDaily();
    if (typeof loadAccountPerformance === 'function') loadAccountPerformance();
    if (typeof loadPortfolioRisk === 'function') loadPortfolioRisk();
    if (typeof loadPortfolioFit === 'function') loadPortfolioFit();
    if (typeof loadLedger === 'function') loadLedger();
    if (typeof loadQuantityPlan === 'function') loadQuantityPlan();
  }
  if (page === 'validation') {
    if (typeof loadValidation === 'function') loadValidation();
    if (typeof loadResearchArchive === 'function') loadResearchArchive();
  }
}
for (const button of document.querySelectorAll('[data-tab]'))
  button.onclick = () => openWorkspace(button.dataset.tab);
function restoreWorkspaceFromLocation() {
  const currentLocation = location.pathname + location.search + location.hash;
  if (currentLocation === lastWorkspaceLocation) return;
  lastWorkspaceLocation = currentLocation;
  openWorkspace(workspaceFromLocation(), false);
}
if (window.addEventListener) {
  window.addEventListener('popstate', restoreWorkspaceFromLocation);
  window.addEventListener('hashchange', restoreWorkspaceFromLocation);
}
