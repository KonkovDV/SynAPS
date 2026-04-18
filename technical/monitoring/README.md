# SynAPS Monitoring Pack

Ready-to-import observability assets for the control-plane metrics endpoint.

## Contents

- `grafana/synaps-control-plane-slo.dashboard.json`
- `prometheus/synaps-control-plane-alerts.yml`

## Metrics Assumed

The assets assume these exported series from `GET /metrics`:

- `synaps_solve_duration_seconds` (histogram)
- `synaps_solver_runs_total{solver_config,status}` (counter)
- `synaps_feasibility_violations_total{kind}` (counter)
- `synaps_active_windows_gauge` (gauge)
- `synaps_gap_ratio` (gauge)

## Import Steps

1. Prometheus: include `prometheus/synaps-control-plane-alerts.yml` in `rule_files` and reload Prometheus.
2. Grafana: import `grafana/synaps-control-plane-slo.dashboard.json` and map datasource variable `DS_PROMETHEUS`.
3. Validate by checking:
   - dashboard panels populate for the selected time range;
   - alert states become `pending`/`firing` when synthetic thresholds are crossed.

## Suggested First SLO Targets

- p95 solve latency < 120s
- p99 solve latency < 300s
- solver error ratio < 20% over 10m
- average gap ratio < 12% over 20m
