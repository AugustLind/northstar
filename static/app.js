/* API connection and session authentication. UI modules load before bootstrap. */
let state = { positions: [], quotes: {} };
let apiBase = (window.NORTHSTAR_CONFIG && window.NORTHSTAR_CONFIG.apiBase) || '',
  accessKey = '';
try {
  apiBase = sessionStorage.getItem('northstar-api') || apiBase;
  accessKey = sessionStorage.getItem('northstar-key') || '';
} catch (e) {}
function showConnection(message = '') {
  $('#connectionPanel').hidden = false;
  $('#backendAddress').value = apiBase;
  $('#connectionMessage').textContent = message;
}
async function api(path, data) {
  if (location.hostname.endsWith('.github.io') && !apiBase) {
    showConnection('Set your Oracle HTTPS server address to connect.');
    throw Error('Connect to your Oracle server first.');
  }
  const headers = {};
  if (accessKey) headers.Authorization = 'Bearer ' + accessKey;
  const options = { headers, credentials: 'omit' };
  if (data !== undefined) {
    options.method = 'POST';
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(data);
  }
  let r;
  try {
    r = await fetch(apiBase + '/api/' + path, options);
  } catch (e) {
    throw Error(
      'Cannot reach Oracle. Check its HTTPS address, server status and allowed Pages origin.'
    );
  }
  const body = await r.json();
  if (r.status === 401) showConnection(body.error);
  if (!r.ok) throw Error(body.error || 'Request failed');
  return body;
}
$('#connectionButton').onclick = () => showConnection();
$('#disconnect').onclick = () => {
  accessKey = '';
  try {
    sessionStorage.removeItem('northstar-key');
  } catch (e) {}
  $('#accessKey').value = '';
  state = { positions: [], quotes: {} };
  render();
  $('#adviceCards').innerHTML = '';
  $('#commentary').textContent = '';
  $('#answer').textContent = '';
  showConnection('Signed out.');
  location.reload();
};
$('#connectionForm').onsubmit = async (e) => {
  e.preventDefault();
  const address = $('#backendAddress').value.trim().replace(/\/$/, '');
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
    apiBase = address;
    accessKey = $('#accessKey').value.trim();
    await api('state');
    try {
      sessionStorage.setItem('northstar-api', apiBase);
      sessionStorage.setItem('northstar-key', accessKey);
    } catch (e) {}
    $('#accessKey').value = '';
    $('#connectionPanel').hidden = true;
    $('#message').textContent = 'Connected to Oracle.';
    await load();
    if (typeof loadResearch === 'function') await loadResearch();
  } catch (e) {
    $('#connectionMessage').textContent = e.message;
  }
};
