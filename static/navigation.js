/* Workspace router with legacy-hash aliases. Views register before bootstrap. */
const workspaceRoutes = {
  daily: 'daily',
  announcements: 'daily',
  briefing: 'daily',
  method: 'daily',
  recommendations: 'recommendations',
  portfolio: 'portfolio',
  candidates: 'candidates',
  fit: 'portfolio',
  activity: 'portfolio',
  validation: 'validation',
};
const workspaceTitles = {
  daily: 'Overview',
  recommendations: 'Research',
  portfolio: 'Portfolio',
  candidates: 'Candidates',
  validation: 'Strategy lab',
};
function workspaceElement(id) {
  if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) return null;
  return document.getElementById ? document.getElementById(id) : $('#' + id);
}
const workspaceUiStateKey = 'northstar-workspace-ui-v1';
function readWorkspaceUiState() {
  try {
    return JSON.parse(sessionStorage.getItem(workspaceUiStateKey) || '{}');
  } catch (e) {
    return {};
  }
}
function workspaceUiControls() {
  return Array.from(document.querySelectorAll('input, select, textarea')).filter((control) => {
    const workspaceControl = control.closest && control.closest('.tab');
    const editorControl = control.form && control.form.id === 'positionForm';
    return (
      (workspaceControl || editorControl) && control.dataset?.ephemeral === undefined &&
      !['file', 'password', 'hidden', 'button', 'submit', 'reset'].includes(control.type)
    );
  });
}
function workspaceUiControlKey(control) {
  return control.id ||
    (control.form && control.form.id && control.name
      ? control.form.id + '.' + control.name
      : '');
}
function workspaceUiStateHas(formId) {
  const saved = readWorkspaceUiState();
  return workspaceUiControls().some(
    (control) =>
      control.form &&
      control.form.id === formId &&
      Object.prototype.hasOwnProperty.call(saved, workspaceUiControlKey(control))
  );
}
function saveWorkspaceUiState(event) {
  const control = event.target;
  if (!workspaceUiControls().includes(control)) return;
  const controls = readWorkspaceUiState();
  const related = control.form
    ? workspaceUiControls().filter((item) => item.form === control.form)
    : [control];
  for (const item of related) {
    const key = workspaceUiControlKey(item);
    if (!key) continue;
    controls[key] = {
      value: item.value,
      checked: item.type === 'checkbox' || item.type === 'radio' ? item.checked : undefined,
      readOnly: item.readOnly,
    };
  }
  try {
    sessionStorage.setItem(workspaceUiStateKey, JSON.stringify(controls));
  } catch (e) {}
}
function restoreWorkspaceUiState(formId) {
  const savedControls = readWorkspaceUiState();
  for (const control of workspaceUiControls()) {
    if (formId && (!control.form || control.form.id !== formId)) continue;
    const saved = savedControls[workspaceUiControlKey(control)];
    if (!saved) continue;
    if (control.type === 'checkbox' || control.type === 'radio') control.checked = !!saved.checked;
    else control.value = saved.value;
    if (typeof saved.readOnly === 'boolean') control.readOnly = saved.readOnly;
  }
  if (!formId && workspaceUiStateHas('positionForm')) {
    const editor = workspaceElement('editor');
    if (editor && editor.showModal && !editor.open) editor.showModal();
  }
}
function clearWorkspaceUiState() {
  try {
    sessionStorage.removeItem(workspaceUiStateKey);
  } catch (e) {}
}
restoreWorkspaceUiState();
if (document.addEventListener) {
  document.addEventListener('input', saveWorkspaceUiState, true);
  document.addEventListener('change', saveWorkspaceUiState, true);
}
let lastWorkspaceLocation = location.pathname + location.search + location.hash;
function workspaceFromLocation() {
  const hashTarget = location.hash ? location.hash.slice(1) : '';
  return hashTarget && (workspaceRoutes[hashTarget] || workspaceElement(hashTarget))
    ? hashTarget
    : location.pathname === '/recommendations'
    ? 'recommendations'
    : 'portfolio';
}
function openWorkspace(target, updateHistory = true) {
  const destination = workspaceElement(target);
  const section = destination && destination.closest ? destination.closest('.tab') : null;
  const page = workspaceRoutes[target] || (section && section.id) || 'daily';
  if (!destination) target = page;
  $('#workspaceTitle').textContent = workspaceTitles[page];
  for (const section of document.querySelectorAll('.tab')) section.hidden = section.id !== page;
  for (const button of document.querySelectorAll('[data-tab]')) {
    const primary = page === 'recommendations' || page === 'validation' ? 'candidates' : page;
    const active = button.dataset.tab === primary;
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
  if (page === 'daily' || page === 'candidates') {
    if (typeof loadDaily === 'function') loadDaily();
  }
  if (page === 'daily') {
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
function clearWorkspaceUiFormState(formId) {
  const saved = readWorkspaceUiState();
  for (const control of workspaceUiControls()) {
    if (control.form && control.form.id === formId) delete saved[workspaceUiControlKey(control)];
  }
  try {
    sessionStorage.setItem(workspaceUiStateKey, JSON.stringify(saved));
  } catch (e) {}
}
for (const button of document.querySelectorAll('[data-tab]'))
  button.onclick = () => openWorkspace(button.dataset.tab);
for (const button of document.querySelectorAll('[data-open]'))
  button.onclick = () => openWorkspace(button.dataset.open);
function restoreWorkspaceFromLocation() {
  const currentLocation = location.pathname + location.search + location.hash;
  if (currentLocation === lastWorkspaceLocation) return;
  lastWorkspaceLocation = currentLocation;
  openWorkspace(workspaceFromLocation(), false);
}
if (window.addEventListener) {
  window.addEventListener('pageshow', () => restoreWorkspaceUiState());
  window.addEventListener('popstate', restoreWorkspaceFromLocation);
  window.addEventListener('hashchange', restoreWorkspaceFromLocation);
}
