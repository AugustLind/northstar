/* Start requests only after every view and controller has been defined. */
initExplorer();
initChartTools();
openWorkspace(workspaceFromLocation(), false);
load()
  .then(() => {
    if (!location.hash && workspaceFromLocation() === 'portfolio') openWorkspace('portfolio', false);
  })
  .catch((e) => ($('#message').textContent = e.message));
loadResearch().finally(restoreWorkspaceUiState);
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

$('#startPortfolio').onclick = () => {
  openWorkspace('portfolio');
  $('#add').focus();
};
$('#startResearch').onclick = () => openWorkspace('recommendations');
$('#startLedger').onclick = () => openWorkspace('activity');
