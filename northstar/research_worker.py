"""Background orchestration for research reports and their lifecycle."""
import threading
import time

from northstar import advice_state
from northstar import research
from northstar import trade_plan


class ResearchWorker:
    def __init__(self, refresh, snapshot, read, write, settings, on_report=None, on_archive=None):
        self.refresh, self.snapshot, self.read, self.write, self.settings = refresh, snapshot, read, write, settings
        self.on_report = on_report
        self.on_archive = on_archive
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.status_lock = threading.Lock()
        self.status = {'running': False, 'last_started': None, 'last_finished': None, 'next_run': None, 'error': None}

    def run_once(self):
        if not self.lock.acquire(blocking=False):
            return False
        with self.status_lock:
            self.status.update(running=True, last_started=time.time(), error=None)
        try:
            settings = self.settings()
            errors = self.refresh(settings['universe'])
            snapshot = self.snapshot()
            report = research.build_report(snapshot, settings['universe'], settings.get('min_turnover_nok', 250000),
                                           promoted_model=self.read('promoted_experiment_model', None))
            signal_state = advice_state.observe(report, self.read('signal_state', {}), report['generated'])
            self.write('signal_state', signal_state)
            snapshot['signal_state'] = signal_state
            report['trade_plan'] = trade_plan.build(snapshot, report, snapshot.get('portfolio_preferences', {}))
            quantities, changes = advice_state.differences(
                report['trade_plan'], self.read('advice_quantities', {}),
                snapshot.get('portfolio_preferences', {}).get('min_change_pct', 20), report['generated'])
            self.write('advice_quantities', quantities)
            report['recommendation_changes'] = changes
            report['errors'] = errors
            if self.on_archive:
                try:
                    report['archive_run_id'] = self.on_archive(report, snapshot, settings)
                except Exception:
                    report['archive_error'] = 'Research input archiving failed; current results retained. Check storage.'
            self.write('report', report)
            if self.on_report:
                self.on_report()
            if settings['llm_enabled']:
                report['llm_status'] = 'generating local briefing'
                # Publish charts/signals immediately, before potentially slow local inference.
                self.write('report', report)
                try:
                    report['commentary'] = research.local_answer(settings['model'], report,
                        'Summarise the leading included buy candidates and any included holding sell reviews. Explain missing coverage. Use at most 150 words.')
                    report['llm_status'] = 'ready'
                    report['model'] = settings['model']
                except Exception as error:
                    report['llm_status'] = research.llm_error(error, settings['model'])
            self.write('report', report)
        except Exception as error:
            with self.status_lock:
                self.status['error'] = type(error).__name__ + ': analysis failed; previous report retained'
        finally:
            with self.status_lock:
                self.status.update(running=False, last_finished=time.time(),
                                   next_run=time.time() + self.settings()['interval_minutes'] * 60)
            self.lock.release()
        return True

    def trigger(self):
        self.wake.set()

    def loop(self):
        while not self.stop.is_set():
            self.wake.clear()
            self.run_once()
            self.wake.wait(self.settings()['interval_minutes'] * 60)

    def start(self):
        threading.Thread(target=self.loop, name='northstar-research', daemon=True).start()

    def view(self):
        with self.status_lock:
            status = dict(self.status)
        report = self.read('report', None)
        if report and (report.get('market_scope') != research.SCOPE
                       or report.get('policy_version') != research.policy.VERSION):
            report = None
        return {'report': report, 'worker': status, 'settings': self.settings(),
                'model_busy': research.MODEL_LOCK.locked(),
                'progress': self.read('refresh_progress', None),
                'default_universe': research.DEFAULT_UNIVERSE,
                'fundamentals_progress': self.read('fundamentals_progress', None)}
