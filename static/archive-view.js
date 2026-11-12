/* Private, read-only research evidence and replay. Does not change holdings or trigger alerts. */
let archiveRequest = 0;
async function loadResearchArchive() {
  const token = ++archiveRequest;
  const text = $('#archiveBefore').value;
  let suffix = '';
  if (text) {
    const stamp = Date.parse(text) / 1000;
    if (!Number.isFinite(stamp)) {
      $('#archiveStatus').textContent = 'Choose a valid capture cutoff.';
      return;
    }
    suffix = '?before=' + encodeURIComponent(stamp);
  }
  try {
    const value = await api('archive' + suffix);
    if (token !== archiveRequest) return;
    $('#archiveStatus').textContent =
      value.error ||
      'Append-only input observations. Historical provider dates do not imply earlier capture.';
    $('#archiveSummary').innerHTML =
      (value.kinds || [])
        .map((k) =>
          toolTile(
            k.kind,
            String(k.observations),
            'First captured ' + new Date(k.first_capture * 1000).toLocaleString()
          )
        )
        .join('') +
      toolTile(
        'Compressed storage',
        toolNumber((value.compressed_bytes || 0) / 1048576, ' MiB', 2),
        'Current total storage; dated lists use the cutoff'
      ) +
      toolTile(
        'Price-bar versions',
        String(value.price_versions || 0),
        'Unchanged historical bars are shared'
      );
    const select = $('#archiveRun'),
      previous = select.value;
    select.innerHTML =
      '<option value="">Choose a captured research run</option>' +
      (value.runs || [])
        .map(
          (r) =>
            '<option value="' +
            Number(r.id) +
            '">' +
            esc(new Date(r.captured * 1000).toLocaleString()) +
            ' · run ' +
            Number(r.id) +
            '</option>'
        )
        .join('');
    if ((value.runs || []).some((r) => String(r.id) === previous)) select.value = previous;
    $('#replayArchive').disabled = !select.value;
    $('#archiveMethod').textContent = value.method;
  } catch (error) {
    if (token === archiveRequest) $('#archiveStatus').textContent = error.message;
  }
}
$('#refreshArchive').onclick = loadResearchArchive;
$('#archiveBefore').onchange = loadResearchArchive;
$('#archiveRun').onchange = () => {
  $('#replayArchive').disabled = !$('#archiveRun').value;
};
$('#replayArchive').onclick = async () => {
  const id = Number($('#archiveRun').value);
  if (!Number.isSafeInteger(id) || id < 1) return;
  $('#replayArchive').disabled = true;
  try {
    const value = await api('archive/replay?id=' + id);
    $('#archiveReplayStatus').textContent =
      'Captured ' +
      new Date(value.captured * 1000).toLocaleString() +
      ' · ' +
      (value.same_analysis_code
        ? 'Same analysis-source fingerprint.'
        : 'Analysis source has changed; this comparison uses current code.') +
      ' ' +
      value.differences +
      ' ranking/action/score difference(s). ' +
      value.method;
    $('#archiveReplayRows').innerHTML = toolTable(
      [
        'Stock',
        'Recorded rank',
        'Replayed rank',
        'Recorded action',
        'Replayed action',
        'Recorded score',
        'Replayed score',
      ],
      value.rows.map((r) => [
        esc(r.symbol),
        esc(r.saved_rank || '—'),
        esc(r.replayed_rank || '—'),
        esc(r.saved_action),
        esc(r.replayed_action),
        esc(toolNumber(r.saved_score)),
        esc(toolNumber(r.replayed_score)),
      ])
    );
  } catch (error) {
    $('#archiveReplayStatus').textContent = error.message;
  } finally {
    $('#replayArchive').disabled = false;
  }
};
