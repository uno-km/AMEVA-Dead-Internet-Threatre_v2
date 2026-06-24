import time
import threading
from collections import defaultdict

class MetricsRegistry:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(MetricsRegistry, cls).__new__(cls, *args, **kwargs)
                cls._instance._init_registry()
            return cls._instance

    def _init_registry(self):
        self.lock = threading.Lock()
        # 구조: self.counters[metric_name][labels_tuple] = value
        self.counters = defaultdict(float)
        # 구조: self.gauges[metric_name][labels_tuple] = value
        self.gauges = defaultdict(float)
        
        # 메트릭 메타데이터 (HELP, TYPE)
        self.metadata = {
            "dispatch_success_total": ("Counter", "Total number of successful job dispatches"),
            "dispatch_failure_total": ("Counter", "Total number of failed job dispatches"),
            "worker_heartbeat_freshness_seconds": ("Gauge", "Time difference in seconds since the last heartbeat per worker"),
            "event_bus_lag_seconds": ("Gauge", "Event processing lag in seconds"),
            "reconciliation_mismatches_total": ("Counter", "Total number of billing ledger reconciliation mismatches"),
            "action_processing_latency_seconds": ("Gauge", "Latency of processing action events in seconds"),
            "active_websocket_connections": ("Gauge", "Total active websocket connections to the platform")
        }

    def increment(self, metric_name: str, value: float = 1.0, labels: dict = None):
        """카운터 증가"""
        with self.lock:
            labels_tuple = self._dict_to_tuple(labels)
            self.counters[(metric_name, labels_tuple)] += value

    def set_gauge(self, metric_name: str, value: float, labels: dict = None):
        """게이지 설정"""
        with self.lock:
            labels_tuple = self._dict_to_tuple(labels)
            self.gauges[(metric_name, labels_tuple)] = value

    def _dict_to_tuple(self, labels: dict) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def generate_prometheus_format(self) -> str:
        """Prometheus 포맷 텍스트 렌더링 (기본값 설정 추가)"""
        lines = []
        with self.lock:
            for m_name, (m_type, m_help) in self.metadata.items():
                lines.append(f"# HELP {m_name} {m_help}")
                lines.append(f"# TYPE {m_name} {m_type.lower()}")
                
                items = []
                if m_type == "Counter":
                    for (name, labels_tuple), value in self.counters.items():
                        if name == m_name:
                            items.append((labels_tuple, value))
                    if items:
                        for labels_tuple, value in items:
                            label_str = self._format_labels(labels_tuple)
                            lines.append(f"{m_name}{label_str} {value}")
                    else:
                        lines.append(f"{m_name} 0.0")
                elif m_type == "Gauge":
                    for (name, labels_tuple), value in self.gauges.items():
                        if name == m_name:
                            items.append((labels_tuple, value))
                    if items:
                        for labels_tuple, value in items:
                            label_str = self._format_labels(labels_tuple)
                            lines.append(f"{m_name}{label_str} {value}")
                    else:
                        lines.append(f"{m_name} 0")
                        
        return "\n".join(lines) + "\n"

    def _format_labels(self, labels_tuple: tuple) -> str:
        if not labels_tuple:
            return ""
        pairs = [f'{k}="{v}"' for k, v in labels_tuple]
        return "{" + ",".join(pairs) + "}"

# 글로벌 싱글톤 객체 제공
metrics = MetricsRegistry()
