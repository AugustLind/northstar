/* Trading workspace charts over recorded valuations and provider OHLCV. */
const workspacePlots = new Map();
const workspaceStocks = new Map();
const chartDate = new Intl.DateTimeFormat('en-GB', {timeZone:'UTC', day:'numeric', month:'short', year:'numeric'});
const chartShortDate = new Intl.DateTimeFormat('en-GB', {timeZone:'UTC', day:'numeric', month:'short'});
const chartQuantity = new Intl.NumberFormat('en-GB', {maximumFractionDigits:4});
let workspacePurchases = [];

function chartTime(date) {
  return Date.parse(date) / 1000;
}

function clearWorkspaceChart(container, message) {
  workspacePlots.get(container)?.chart.remove();
  workspacePlots.delete(container);
  container.textContent = message;
}

function resetWorkspaceCharts() {
  workspaceStocks.clear();
  workspacePurchases = [];
  for (const container of workspacePlots.keys()) clearWorkspaceChart(container, '');
}

function plotWorkspaceChart(container, {title, detail, currency, stockSymbol, points, days}) {
  const stock = Boolean(stockSymbol);
  const plotted = points.filter(point => Number.isFinite(point.time));
  const usable = plotted.filter(point => Number.isFinite(stock ? point.close : point.value));
  if (!window.LightweightCharts || usable.length < 2) {
    clearWorkspaceChart(container, window.LightweightCharts
      ? 'Chart unavailable. There are fewer than two usable observations.'
      : 'Chart unavailable. Reload the workspace to try again.');
    return;
  }

  const key = JSON.stringify([title, detail, currency, stockSymbol, days]);
  const current = workspacePlots.get(container);
  if (current?.key === key) {
    current.update(plotted, usable);
    return;
  }
  clearWorkspaceChart(container, '');
  const {LightweightCharts: charts} = window;
  container.innerHTML =
    '<div class="plot-caption"><strong>' + esc(title) + '</strong><span>' + esc(detail) + '</span>' +
    '<div class="plot-readout"></div><div class="plot-purchases"></div></div>' +
    '<div class="trading-plot" tabindex="0" role="group" aria-label="' + esc(title) +
    ' chart. Use left and right arrows to inspect, plus and minus to zoom, Home for full history and End for recent data."></div>' +
    '<span class="visually-hidden plot-announcement" role="status"></span>' +
    '<div class="plot-footer"><span class="plot-window"></span><a href="https://www.tradingview.com/">TradingView</a>' +
    '<div class="plot-controls" role="group" aria-label="Chart navigation">' +
    '<button type="button" data-plot="out" aria-label="Zoom out">−</button>' +
    '<button type="button" data-plot="in" aria-label="Zoom in">+</button>' +
    '<button type="button" data-plot="fit">Fit history</button><button type="button" data-plot="latest">Latest</button></div></div>';

  const host = container.querySelector('.trading-plot');
  const readout = container.querySelector('.plot-readout');
  const orders = container.querySelector('.plot-purchases');
  const announcement = container.querySelector('.plot-announcement');
  const windowLabel = container.querySelector('.plot-window');
  const decimal = new Intl.NumberFormat('en-GB', {minimumFractionDigits:stock ? 2 : 0, maximumFractionDigits:stock ? 2 : 0});
  const chart = charts.createChart(host, {
    autoSize:true,
    layout:{background:{color:'#0a0c11'}, textColor:'#aeb7c8', fontSize:12, attributionLogo:false},
    grid:{vertLines:{color:'#1b2130'}, horzLines:{color:'#202635'}},
    crosshair:{mode:charts.CrosshairMode.Normal, vertLine:{color:'#7c879c', labelBackgroundColor:'#323b50'},
      horzLine:{color:'#7c879c', labelBackgroundColor:'#323b50'}},
    rightPriceScale:{borderColor:'#30394b', minimumWidth:67, scaleMargins:{top:.09,bottom:stock ? .27 : .12}},
    timeScale:{borderColor:'#30394b', rightOffset:3, minBarSpacing:.02, lockVisibleTimeRangeOnResize:true},
    localization:{timeFormatter:time => chartDate.format(time*1000)},
    handleScroll:{vertTouchDrag:false},
  });
  const priceFormat = {type:'custom', minMove:stock ? .01 : 1, formatter:value=>decimal.format(value)};
  const price = stock
    ? chart.addSeries(charts.CandlestickSeries, {priceFormat, upColor:'#36b49a', downColor:'#e37480',
        borderVisible:false, wickUpColor:'#36b49a', wickDownColor:'#e37480'})
    : chart.addSeries(charts.AreaSeries, {priceFormat, lineColor:'#86a6ff', topColor:'rgba(92,129,255,.30)',
        bottomColor:'rgba(92,129,255,0)', lineWidth:2});
  const volume = stock ? chart.addSeries(charts.HistogramSeries, {
    priceScaleId:'volume', priceFormat:{type:'volume'}, priceLineVisible:false, lastValueVisible:false,
  }) : null;
  if (volume) volume.priceScale().applyOptions({scaleMargins:{top:.80,bottom:0}});
  const markers = charts.createSeriesMarkers(price, []);
  const scale = chart.timeScale();
  let data = [], observations = [], indexes = new Map(), purchases = new Map(), inspected = 0;
  let waitingForSize = false;

  function pointValue(point) {
    return stock ? point.close : point.value;
  }
  function showPoint(index, speak = false) {
    const point = data[index];
    if (!point) return;
    inspected = index;
    const date = chartDate.format(point.time*1000);
    const fields = !Number.isFinite(pointValue(point)) ? [['Valuation','Unavailable']] : stock
      ? [['O',decimal.format(point.open)],['H',decimal.format(point.high)],
          ['L',decimal.format(point.low)],['C',decimal.format(point.close)],
          ['Vol',point.volume == null ? 'Unavailable' : chartQuantity.format(point.volume)]]
      : [['Value',decimal.format(point.value) + ' ' + currency]];
    readout.innerHTML = '<time datetime="' + new Date(point.time*1000).toISOString() + '">' + date + '</time>' +
      fields.map(([label,value])=>'<span>'+label+' <b>'+value+'</b></span>').join('');
    const summaries = (purchases.get(point.time) || []).map(order=>{
      const execution = order.fee == null ? null : (-order.net_cash-order.fee)/order.quantity;
      return 'Bought ' + chartQuantity.format(order.quantity) + ' ' + order.symbol +
        (execution == null || !Number.isFinite(execution) || execution < 0
          ? ' · execution price unavailable' : ' at ' + money(execution,order.currency) + ' per share');
    });
    orders.textContent = summaries.join(' · ');
    if (speak) {
      const labels = {O:'Open',H:'High',L:'Low',C:'Close',Vol:'Volume'};
      announcement.textContent = [date,...fields.map(([label,value])=>(labels[label]||label)+' '+value),...summaries].join('. ');
    }
  }
  function latest() {
    if (!data.length) return;
    if (!host.clientWidth) {
      waitingForSize = true;
      return;
    }
    waitingForSize = false;
    const end = data.length-1;
    const firstDate = data[end].time - (days-1)*86400;
    const first = Math.max(0, data.findIndex(point=>point.time>=firstDate));
    chart.clearCrosshairPosition();
    scale.setVisibleLogicalRange({from:Math.min(first,end-1)-.5,to:end+3});
    showPoint(indexes.get(observations.at(-1).time));
  }
  function fit() {
    scale.setVisibleLogicalRange({from:-.5,to:data.length+2});
  }
  function zoom(factor) {
    const range = scale.getVisibleLogicalRange();
    if (!range) return;
    const width = Math.min(data.length+2.5, Math.max(2,(range.to-range.from)*factor));
    const center = inspected >= range.from && inspected <= range.to ? inspected : (range.from+range.to)/2;
    const from = Math.max(-.5,Math.min(data.length+2-width,center-width/2));
    scale.setVisibleLogicalRange({from,to:from+width});
  }
  function inspect(index) {
    const point = data[index];
    const range = scale.getVisibleLogicalRange();
    if (range && (index<range.from || index>range.to)) {
      const width = range.to-range.from;
      scale.setVisibleLogicalRange({from:index-width/2,to:index+width/2});
    }
    if (Number.isFinite(pointValue(point))) chart.setCrosshairPosition(pointValue(point),point.time,price);
    else chart.clearCrosshairPosition();
    showPoint(index,true);
  }
  function update(next, available) {
    const range = scale.getVisibleLogicalRange();
    const previousStart = data[0]?.time;
    const previousInspection = data[inspected]?.time;
    data = next;
    observations = available;
    indexes = new Map(data.map((point,index)=>[point.time,index]));
    price.setData(data.map(point=>Number.isFinite(pointValue(point))
      ? stock ? {time:point.time,open:point.open,high:point.high,low:point.low,close:point.close}
        : {time:point.time,value:point.value}
      : {time:point.time}));
    if (volume) volume.setData(data.map(point=>point.volume == null ? {time:point.time}
      : {time:point.time,value:point.volume,color:point.close>=point.open ? '#285b54' : '#71444e'}));
    updatePurchases();
    const offset = indexes.get(previousStart);
    if (range && offset != null) {
      scale.setVisibleLogicalRange({from:range.from+offset,to:range.to+offset});
      showPoint(indexes.get(previousInspection) ?? data.length-1);
    } else latest();
  }
  function updatePurchases() {
    purchases = new Map();
    for (const order of workspacePurchases) {
      if (stock && order.symbol !== stockSymbol) continue;
      const time = chartTime(order.date);
      const point = data[indexes.get(time)];
      if (!point || !Number.isFinite(pointValue(point))) continue;
      if (!purchases.has(time)) purchases.set(time,[]);
      purchases.get(time).push(order);
    }
    markers.setMarkers([...purchases.keys()].sort((a,b)=>a-b).map(time=>({
      time,position:'inBar',shape:'circle',size:.65,color:'#e8bd78',
    })));
    if (data[inspected]) showPoint(inspected);
  }

  chart.subscribeCrosshairMove(event=>{
    if (indexes.has(event.time)) showPoint(indexes.get(event.time));
  });
  scale.subscribeSizeChange(()=>{ if (waitingForSize) latest(); });
  scale.subscribeVisibleLogicalRangeChange(range=>{
    if (!range || !data.length) return;
    const at = index => data[Math.max(0,Math.min(data.length-1,index))];
    const start = chartShortDate.format(at(Math.ceil(range.from)).time*1000);
    const end = chartDate.format(at(Math.floor(range.to)).time*1000);
    windowLabel.textContent = start + ' – ' + end + ' · Oslo dates';
  });
  const actions = {in:()=>zoom(.7),out:()=>zoom(1/.7),fit,latest};
  container.querySelector('.plot-controls').onclick = event=>actions[event.target.dataset.plot]?.();
  host.onkeydown = event=>{
    const key = event.key;
    if (key === 'ArrowLeft' || key === 'ArrowRight') {
      inspect(Math.max(0,Math.min(data.length-1,inspected+(key === 'ArrowLeft' ? -1 : 1))));
    } else {
      const action = {'+':'in','=':'in','-':'out',Home:'fit',End:'latest'}[key];
      if (!action) return;
      actions[action]();
    }
    event.preventDefault();
  };
  workspacePlots.set(container,{key,chart,update,updatePurchases});
  update(plotted,usable);
}

function renderOverviewChart(value) {
  workspacePurchases = Array.isArray(value.chart_purchases) ? value.chart_purchases : [];
  const chart = $('#overviewChart');
  const dates = new Map();
  if (value.status === 'available' || value.status === 'estimated') {
    for (const point of value.curve || []) dates.set(point.date,point.value_nok);
  }
  for (const point of value.last_7_days?.curve || []) dates.set(point.date,point.value_nok);
  const points = [...dates].sort(([a],[b])=>a.localeCompare(b)).map(([date,amount])=>({time:chartTime(date),value:amount}));
  plotWorkspaceChart(chart,{title:'Account value',detail:'NOK · Daily valuations · Includes external cash flows',
    currency:'NOK',points,days:7});
  workspacePlots.forEach((plot, container)=>{ if (container !== chart) plot.updatePurchases(); });
}

async function showWorkspaceStock(container, symbol) {
  if (workspaceStocks.get(container)?.symbol === symbol) return;
  const request = {symbol};
  workspaceStocks.set(container, request);
  if (!symbol) {
    clearWorkspaceChart(container,'Choose a company to view price and volume.');
    return;
  }
  clearWorkspaceChart(container,'Loading daily price and volume…');
  try {
    const quote = await api('history?symbol=' + encodeURIComponent(symbol));
    if (workspaceStocks.get(container) !== request) return;
    const points = (quote.history || []).filter(point=>[point.time,point.open,point.high,point.low,point.close].every(Number.isFinite));
    // Chart timestamps identify Oslo reporting dates, not intraday execution times.
    const bars = new Map(points.map(point=>{
      const time = Math.floor(point.time/86400)*86400;
      return [time,{...point,time}];
    }));
    const currency = quote.currency || 'NOK';
    const ledgerSymbol = currency === 'NOK' && !symbol.includes('.') ? symbol + '.OL' : symbol;
    plotWorkspaceChart(container,{title:symbol,detail:currency+' · Daily · '+(quote.history_basis || 'Provider prices'),
      currency,stockSymbol:ledgerSymbol,points:[...bars.values()].sort((a,b)=>a.time-b.time),days:60});
  } catch (error) {
    if (workspaceStocks.get(container) !== request) return;
    workspaceStocks.delete(container);
    clearWorkspaceChart(container,error.message);
  }
}
