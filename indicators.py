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
    liquid=turnover is not None and turnover_days>=15 and turnover>=floor
    liquidity_score=clamp(50+25*math.log10(max(turnover or 1,1)/max(floor,1))) if turnover_days>=15 else 0
    parts=[('Trend',trend_score,30,'Price versus 50/200-session averages and the direction of those averages.'),
           ('Momentum',momentum_score,25,f'3-month {metrics["momentum3m"]:+.1f}%; 6-month {return6m:+.1f}%, scaled by volatility.'),
           ('Risk',risk_score,20,f'Annualised volatility {volatility:.1f}%; maximum historical drawdown {worst:.1f}%.'),
           ('Timing',timing_score,15,f'RSI(14) {strength:.1f}; MACD {"above" if macd[-1]>signal[-1] else "below"} signal; extension {extension:+.1f}%.'),
           ('Liquidity',liquidity_score,10,'20-session average traded value and observation coverage; spreads are not measured.')]
    composite=round(sum(score*weight/100 for _,score,weight,_ in parts),1)
    metrics.update(rsi14=strength,macd=macd[-1],macd_signal=signal[-1],macd_histogram=macd[-1]-signal[-1],
                   bollinger_upper=upper,bollinger_lower=lower,bollinger_mid=mid,momentum6m=return6m,
                   max_drawdown=worst,extension50=extension)
    return {'composite':composite,'rank_eligible':liquid and volatility<80,
            'analyses':[{'name':name,'score':round(score,1),'weight':weight,'explanation':why} for name,score,weight,why in parts],
            'observations':[
                f'RSI(14) is {strength:.1f}: '+('overbought momentum; not an automatic sell' if strength>=70 else 'oversold momentum; not evidence of cheap valuation' if strength<=30 else 'between oversold and overbought thresholds'),
                'MACD is '+('above its signal line.' if macd[-1]>signal[-1] else 'below its signal line.'),
                f'Price is {extension:+.1f}% from the 50-session average.',
                'Price is '+('above the upper' if latest>upper else 'below the lower' if latest<lower else 'inside the')+' 20-session Bollinger band.',
            ]}
