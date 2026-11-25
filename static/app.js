/* API connection and session authentication. UI modules load before bootstrap. */
let state = { positions: [], quotes: {} };
const rememberedSessionKey = 'northstar-remembered-session';
const configuredApi = (window.NORTHSTAR_CONFIG && window.NORTHSTAR_CONFIG.apiBase) || '';
let apiBase = configuredApi,
  accessKey = '',
  rememberedSession = readRememberedSession();
try {
  accessKey = sessionStorage.getItem('northstar-key') || '';
  apiBase = sessionStorage.getItem('northstar-api') ?? configuredApi;
} catch (e) {}
if (!accessKey && rememberedSession) {
  apiBase = rememberedSession.origin;
  accessKey = rememberedSession.token;
}

function showConnection(message = '') {
  $('#connectionPanel').hidden = false;
  $('#backendAddress').value = apiBase;
  $('#connectionMessage').textContent = message;
}
function readRememberedSession() {
  try {
    return JSON.parse(window.localStorage.getItem(rememberedSessionKey) || 'null');
  } catch (e) {
    return null;
  }
}
function forgetRememberedSession(session) {
  try {
    if (readRememberedSession()?.token === session.token)
      window.localStorage.removeItem(rememberedSessionKey);
  } catch (e) {}
  rememberedSession = null;
}
function finishSignOut() {
  accessKey = '';
  try {
    sessionStorage.removeItem('northstar-key');
  } catch (e) {}
  clearWorkspaceUiState();
  location.reload();
}

async function api(path, data, origin = apiBase, credential = accessKey) {
  if (location.hostname.endsWith('.github.io') && !origin) {
    showConnection('Set your Oracle HTTPS server address to connect.');
    throw Error('Connect to your Oracle server first.');
  }
  const headers = {};
  if (credential) headers.Authorization = 'Bearer ' + credential;
  const options = { headers, credentials: 'omit' };
  if (path.startsWith('session/')) options.redirect = 'error';
  if (data !== undefined) {
    options.method = 'POST';
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(data);
  }
  let r;
  try {
    r = await fetch(origin + '/api/' + path, options);
  } catch (e) {
    throw Error(
      'Cannot reach your Northstar server. Check your connection and server address, then try again. If the problem continues, ask the server owner to check HTTPS and the allowed dashboard origin.'
    );
  }
  const body = await r.json();
  if (r.status === 401) {
    if (path === 'session/sign-out') return;
    if (credential === accessKey && origin === apiBase) {
      if (rememberedSession && credential === rememberedSession.token) {
        forgetRememberedSession(rememberedSession);
        finishSignOut();
      }
      showConnection(body.error);
    }
  }
  if (!r.ok) throw Error(body.error || 'Request failed');
  return body;
}

async function revokeRememberedSession() {
  const session = readRememberedSession() || rememberedSession;
  if (!session) return;
  await api('session/sign-out', {}, session.origin, session.token);
  forgetRememberedSession(session);
}

$('#connectionButton').onclick = () => showConnection();
let changingConnection = false;
if (window.addEventListener) {
  window.addEventListener('storage', (event) => {
    if (event.key === rememberedSessionKey && rememberedSession && !changingConnection)
      finishSignOut();
  });
}
$('#disconnect').onclick = async () => {
  if (changingConnection) return;
  changingConnection = true;
  try {
    await revokeRememberedSession();
    finishSignOut();
  } catch (e) {
    showConnection('Sign-out failed. ' + e.message);
    changingConnection = false;
  }
};
$('#connectionForm').onsubmit = async (e) => {
  e.preventDefault();
  if (changingConnection) return;
  changingConnection = true;
  const address = $('#backendAddress').value.trim().replace(/\/$/, '');
  const key = $('#accessKey').value.trim();
  try {
    if (address) {
      const u = new URL(address);
      if (
        u.protocol !== 'https:' ||
        u.pathname !== '/' ||
        u.username ||
        u.password ||
        u.search ||
        u.hash
      )
        throw Error('Use an HTTPS server origin, such as https://northstar.example.com.');
    } else if (location.hostname.endsWith('.github.io'))
      throw Error('An HTTPS Oracle address is required.');
    await api('state', undefined, address, key);
    await revokeRememberedSession();
    let credential = key;
    if ($('#rememberBrowser').checked) {
      const { token } = await api('session/remember', {}, address, key);
      const session = { origin: address, token };
      try {
        window.localStorage.setItem(rememberedSessionKey, JSON.stringify(session));
      } catch (error) {
        await api('session/sign-out', {}, address, token);
        throw Error('This browser could not store your remembered sign-in.');
      }
      rememberedSession = session;
      credential = token;
    }
    apiBase = address;
    accessKey = credential;
    try {
      sessionStorage.setItem('northstar-api', apiBase);
      if (rememberedSession) sessionStorage.removeItem('northstar-key');
      else sessionStorage.setItem('northstar-key', accessKey);
    } catch (e) {}
    $('#accessKey').value = '';
    $('#rememberBrowser').checked = false;
    $('#connectionPanel').hidden = true;
    $('#message').textContent = 'Connected to Northstar.';
    await load();
    if (typeof loadResearch === 'function') await loadResearch();
    openWorkspace(workspaceFromLocation(), false);
  } catch (e) {
    showConnection(e.message);
  } finally {
    changingConnection = false;
  }
};
