/* Start requests only after every view and controller has been defined. */
initExplorer();
initChartTools();
openWorkspace(
  location.hash
    ? location.hash.slice(1)
    : location.pathname === '/recommendations'
    ? 'recommendations'
    : 'daily',
  false
);
load().catch((e) => ($('#message').textContent = e.message));
loadResearch();
loadSystemStatus();
setInterval(() => {
  loadResearch();
  load().catch(() => {});
}, 15000);
setInterval(() => {
  if (!$('#daily').hidden) loadSystemStatus();
}, 60000);
$('#checkStockFit').onclick = () => {
  if (!explorerSymbol) return;
  openWorkspace('fit');
  $('#fitPreviewSymbol').value = explorerSymbol;
  $('#fitPreviewAmount').value = (researchView.report.portfolio_limits || {}).purchase_nok || 0;
  previewFitPurchase();
};
