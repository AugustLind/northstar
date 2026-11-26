"""Deterministic technical measurements and transparent, unvalidated ranking."""
import math


def ema(values, period):
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1-alpha) * result[-1])
    return result


def rsi(values, period=14):
    changes = [values[i]-values[i-1] for i in range(1,len(values))]
    gains = sum(max(v,0) for v in changes[:period])/period
    losses = sum(max(-v,0) for v in changes[:period])/period
    for v in changes[period:]:
        gains = (gains*(period-1)+max(v,0))/period
        losses = (losses*(period-1)+max(-v,0))/period
    return 50 if gains == losses == 0 else 100 if losses == 0 else 100-100/(1+gains/losses)


def clamp(value):
    return max(0,min(100,value))


def analyse(history, metrics, trend_score, turnover, turnover_days, floor):
    closes = [p['close'] for p in history]
    latest = closes[-1]
    short, long = ema(closes,12), ema(closes,26)
    macd = [a-b for a,b in zip(short,long)]
    signal = ema(macd,9)
    strength = rsi(closes)
    mid = sum(closes[-20:])/20
    sd = math.sqrt(sum((v-mid)**2 for v in closes[-20:])/20)
    upper, lower = mid+2*sd, mid-2*sd
    return6m = (latest/closes[-127]-1)*100
    peak=closes[0];worst=0
    for v in closes:
        peak=max(peak,v);worst=min(worst,(v/peak-1)*100)
    extension = (latest/metrics['ma50']-1)*100
    volatility=metrics['volatility']
    momentum_score=clamp(50+25*(.6*metrics['momentum3m']+.4*return6m)/max(volatility,10))
    risk_score=clamp(100-.8*volatility+.5*worst)
    timing_score=(90 if 40<=strength<=65 else 65 if 30<=strength<70 else 35)
    timing_score=clamp(timing_score+(10 if macd[-1]>signal[-1] else -10)-(20 if extension>=15 else 0))
    liquidity_score=clamp(50+25*math.log10(max(turnover or 1,1)/max(floor,1))) if turnover_days>=15 else 0
    parts=[('Trend',trend_score,30,'Price versus 50/200-session averages and the direction of those averages.'),
           ('Momentum',momentum_score,25,f'3-month {metrics["momentum3m"]:+.1f}%; 6-month {return6m:+.1f}%, scaled by volatility.'),
           ('Risk',risk_score,20,f'Annualised volatility {volatility:.1f}%; maximum historical drawdown {worst:.1f}%.'),
           ('Timing',timing_score,15,f'RSI(14) {strength:.1f}; MACD {"above" if macd[-1]>signal[-1] else "below"} signal; extension {extension:+.1f}%.'),
           ('Liquidity',liquidity_score,10,'20-session average traded value and observation coverage; spreads are not measured.')]
    composite=round(sum(score*weight/100 for _,score,weight,_ in parts),1)
    metrics.update(risk_diagnostics(history))
    metrics.update(rsi14=strength,macd=macd[-1],macd_signal=signal[-1],macd_histogram=macd[-1]-signal[-1],
                   bollinger_upper=upper,bollinger_lower=lower,bollinger_mid=mid,momentum6m=return6m,
                   max_drawdown=worst,extension50=extension)
    return {'composite':composite,
            'analyses':[{'name':name,'score':round(score,1),'weight':weight,'explanation':why} for name,score,weight,why in parts],
            'observations':[
                f'RSI(14) is {strength:.1f}: '+('overbought momentum; not an automatic sell' if strength>=70 else 'oversold momentum; not evidence of cheap valuation' if strength<=30 else 'between oversold and overbought thresholds'),
                'MACD is '+('above its signal line.' if macd[-1]>signal[-1] else 'below its signal line.'),
                f'Price is {extension:+.1f}% from the 50-session average.',
                'Price is '+('above the upper' if latest>upper else 'below the lower' if latest<lower else 'inside the')+' 20-session Bollinger band.',
            ]}


def risk_diagnostics(history):
    """Descriptive daily-close statistics; never inputs to the entry policy.

    Windows count observations, not calendar days. Risk uses at most 252 returns.
    Tail loss averages exactly the worst 5% probability mass (fractional boundary).
    Missing OHLC/volume stays unavailable rather than being replaced with closes.
    """
    closes = [p['close'] for p in history]
    if len(closes) < 2:
        return {}
    returns = [b/a-1 for a,b in zip(closes, closes[1:])]
    sample = returns[-252:]
    def vol(values):
        if len(values) < 2:
            return None
        mean = sum(values)/len(values)
        return math.sqrt(sum((v-mean)**2 for v in values)/(len(values)-1)*252)*100
    peak = closes[-min(len(closes),253)]
    worst = 0
    underwater = longest = 0
    for close in closes[-253:]:
        peak = max(peak, close)
        dd = (close/peak-1)*100
        worst = min(worst, dd)
        underwater = underwater+1 if dd < -1e-10 else 0
        longest = max(longest, underwater)
    ordered = sorted(sample)
    # Linear interpolation for the empirical 5th percentile.
    at = (len(ordered)-1)*.05
    lower = int(at)
    quantile = ordered[lower]+(ordered[min(lower+1,len(ordered)-1)]-ordered[lower])*(at-lower)
    mass = len(ordered)*.05
    whole = int(mass)
    tail = (sum(ordered[:whole])+(mass-whole)*ordered[whole])/mass
    recent = closes[-252:]
    mean = sum(sample)/len(sample)
    sd = vol(sample)
    downside = math.sqrt(sum(min(r,0)**2 for r in sample)/len(sample)*252)*100
    # Log-price least squares: a descriptive trend fit, never extrapolated.
    logs = [math.log(v) for v in closes[-63:]]
    centre = (len(logs)-1)/2
    logmean = sum(logs)/len(logs)
    slope = sum((i-centre)*(v-logmean) for i,v in enumerate(logs))/sum((i-centre)**2 for i in range(len(logs)))
    total = sum((v-logmean)**2 for v in logs)
    residual = sum((v-logmean-slope*(i-centre))**2 for i,v in enumerate(logs))
    path = sum(abs(b-a) for a,b in zip(closes[-21:],closes[-20:])) if len(closes)>=21 else None
    result = {
        'risk_sessions':len(sample), 'return1w':None, 'return1m':None,
        'return3m':None, 'return6m':None, 'return1y':None,
        'volatility20':vol(returns[-20:]) if len(returns)>=20 else None,
        'volatility63':vol(returns[-63:]) if len(returns)>=63 else None,
        'volatility252':sd, 'downside_volatility':downside,
        'sharpe_zero_rate':mean*252/(sd/100) if sd and sd>1e-10 else None,
        'sortino_zero_rate':mean*252/(downside/100) if downside>1e-10 else None,
        'var95_loss':max(0,-quantile*100), 'expected_shortfall95':max(0,-tail*100),
        'max_drawdown1y':worst, 'drawdown1y':(closes[-1]/max(closes[-253:])-1)*100,
        'recovery_pct':(max(closes[-253:])/closes[-1]-1)*100,
        'underwater_sessions':underwater, 'longest_underwater_sessions':longest,
        'high252':max(recent), 'low252':min(recent),
        'range_position':(closes[-1]-min(recent))/(max(recent)-min(recent))*100 if max(recent)>min(recent) else 50,
        'trend_r2':max(0,min(1,1-residual/total)) if total>1e-20 else 0,
        'trend_direction':'rising' if slope>1e-10 else 'falling' if slope < -1e-10 else 'flat',
        'efficiency20':abs(closes[-1]-closes[-21])/path*100 if path else 0 if path==0 else None,
        'atr14':None, 'atr_pct':None, 'adx14':None, 'plus_di14':None, 'minus_di14':None,
        'relative_volume20':None,
    }
    for key, sessions in [('return1w',5),('return1m',21),('return3m',63),('return6m',126),('return1y',252)]:
        if len(closes)>sessions:
            result[key]=(closes[-1]/closes[-sessions-1]-1)*100
    volumes=[p.get('volume') for p in history[-21:]]
    if len(volumes)==21 and all(isinstance(v,(int,float)) and math.isfinite(v) and v>=0 for v in volumes):
        average=sum(volumes[:-1])/20
        result['relative_volume20']=volumes[-1]/average if average>0 else None
    # Require complete valid high/low coverage for Wilder's range/directional series.
    if len(history)>=29 and all(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) and p[k]>0
            for p in history for k in ('high','low')) and all(p['low']<=p['close']<=p['high'] for p in history):
        ranges=[];plus=[];minus=[]
        for prev,point in zip(history,history[1:]):
            ranges.append(max(point['high']-point['low'],abs(point['high']-prev['close']),abs(point['low']-prev['close'])))
            up=point['high']-prev['high'];down=prev['low']-point['low']
            plus.append(up if up>down and up>0 else 0)
            minus.append(down if down>up and down>0 else 0)
        atr=sum(ranges[:14])/14;pos=sum(plus[:14])/14;neg=sum(minus[:14])/14
        dx=[]
        for i in range(13,len(ranges)):
            if i>13:
                atr=(atr*13+ranges[i])/14;pos=(pos*13+plus[i])/14;neg=(neg*13+minus[i])/14
            pdi=100*pos/atr if atr else 0;mdi=100*neg/atr if atr else 0
            dx.append(100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0)
        adx=sum(dx[:14])/14
        for value in dx[14:]:
            adx=(adx*13+value)/14
        result.update(atr14=atr,atr_pct=atr/closes[-1]*100,adx14=adx,plus_di14=pdi,minus_di14=mdi)
    return result
