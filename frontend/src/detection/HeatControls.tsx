import { useDetectionStore } from "./detectionStore";
import {
  currentVersion,
  heatColor,
  previousVersion,
  SIGNAL_ORDER,
  signalLabel,
  TINT_FULL,
  versionsOf,
  type HeatSignal,
} from "./heat";

/** What the call heatmap shows (#59): clinic, version, baseline and signal, and a legend. At the top of the issues panel. */
export function HeatControls() {
  const load = useDetectionStore((s) => s.load);
  const options = useDetectionStore((s) => s.options);
  const setOptions = useDetectionStore((s) => s.setOptions);

  if (load.state !== "ready" || !options) return null;

  const data = load.data;
  const now = currentVersion(data, options.clinic);
  const previous = previousVersion(data, options.clinic, options.version);
  const oldIssues = options.signal === "issues" && Number(options.version) !== now;
  return (
    <div className="heat-controls">
      <div className="heat-selects">
        <label>
          Clinic
          <select value={options.clinic} onChange={(e) => setOptions({ clinic: e.target.value })}>
            {data.clinics.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Version
          <select value={options.version} onChange={(e) => setOptions({ version: e.target.value })}>
            {versionsOf(data, options.clinic).map((v) => (
              <option key={v} value={String(v)}>
                v{v}
                {v === now ? " (now)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Against
          <select
            value={options.compare}
            onChange={(e) => setOptions({ compare: e.target.value as "version" | "fleet" })}
          >
            <option value="version" disabled={previous === null}>
              {previous === null ? "previous version (none)" : `v${previous}`}
            </option>
            <option value="fleet">other clinics</option>
          </select>
        </label>
        <label>
          Show
          <select value={options.signal} onChange={(e) => setOptions({ signal: e.target.value as HeatSignal })}>
            {SIGNAL_ORDER.map((signal) => (
              <option key={signal} value={signal}>
                {signal === "issues" ? "issues found" : signalLabel(data, signal)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="heat-legend">
        <span className="heat-scale" style={{ background: `linear-gradient(90deg, ${heatColor(0)}, ${heatColor(1)})` }} />
        <span className="muted">
          {options.signal === "issues"
            ? "darkest: the node whose issues add the most calls a week, the others in proportion; dashed: no calls; edge width: calls"
            : `tint: points above the baseline, darkest at +${TINT_FULL * 100} or more, only when unlikely to be chance; dashed: no calls; edge width: calls`}
        </span>
      </div>
      {oldIssues && <div className="muted">Issues are for the version running now (v{now}).</div>}
    </div>
  );
}
