/* Authenticated operational health; never requests or sends an email. */
let systemStatusRequest = 0;
async function loadSystemStatus() {
  const token = ++systemStatusRequest;
  try {
    const v = await api('system-status');
    if (token !== systemStatusRequest) return;
    renderSystemStatus(v);
  } catch (e) {
    if (token === systemStatusRequest) $('#systemStatus').textContent = e.message;
  }
}
function renderSystemStatus(v) {
  $('#systemStatus').textContent =
    (v.state === 'ready'
      ? 'Services and data checks ready.'
      : 'Some services or data need attention.') +
    ' Updated ' +
    new Date(v.generated * 1000).toLocaleString() +
    ' · Process uptime ' +
    Math.floor(v.uptime_seconds / 60) +
    ' minutes.';
  $('#systemComponents').innerHTML = (v.components || [])
    .map(
      (c) =>
        '<article><div><strong>' +
        esc(c.label) +
        '</strong><span class="healthbadge ' +
        (c.state === 'ready' ? 'healthy' : c.state === 'running' ? 'working' : 'attention') +
        '">' +
        esc(c.state) +
        '</span></div><p>' +
        esc(c.detail) +
        '</p><small>' +
        (c.last_success
          ? 'Last success: ' + esc(new Date(c.last_success * 1000).toLocaleString()) + '. '
          : '') +
        esc(c.action) +
        '</small></article>'
    )
    .join('');
  $('#workerStatus').innerHTML = toolTable(
    ['Worker', 'Process state'],
    (v.workers || []).map((w) => [esc(w.name), esc(w.state)])
  );
  $('#emailHistory').innerHTML = (v.email_history || []).length
    ? toolTable(
        ['Created', 'Kind / stock', 'State', 'Attempts', 'Next retry / accepted', 'Result'],
        v.email_history.map((e) => [
          esc(new Date(e.created * 1000).toLocaleString()),
          esc(e.kind + (e.symbol ? ' · ' + e.symbol : '')),
          esc(e.status === 'sent' ? 'Accepted by SMTP' : e.status),
          String(e.attempts),
          esc(
            e.sent
              ? new Date(e.sent * 1000).toLocaleString()
              : e.status === 'pending' && e.next_attempt
              ? new Date(e.next_attempt * 1000).toLocaleString()
              : '—'
          ),
          esc(e.last_error || ''),
        ])
      )
    : '<p>No email events for the current configured destination. Configure email and send a test from Overview to verify SMTP acceptance.</p>';
}
$('#refreshSystemStatus').onclick = loadSystemStatus;
