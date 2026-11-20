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
let lastWorkspaceLocation = location.pathname + location.search + location.hash;
function workspaceFromLocation() {
  return location.hash
    ? location.hash.slice(1)
    : location.pathname === '/recommendations'
    ? 'recommendations'
    : 'daily';
}
function openWorkspace(target, updateHistory = true) {
  if (!Object.prototype.hasOwnProperty.call(workspaceRoutes, target)) target = 'daily';
  const page = workspaceRoutes[target] || 'daily';
  $('#workspaceTitle').textContent = workspaceTitles[page];
  for (const section of document.querySelectorAll('.tab')) section.hidden = section.id !== page;
  for (const button of document.querySelectorAll('[data-tab]')) {
    const active = button.dataset.tab === page;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (target !== page) {
    const group = $('#' + target + 'Group');
    if (group) group.open = true;
    const section = $('#' + target);
    if (section && section.scrollIntoView)
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
