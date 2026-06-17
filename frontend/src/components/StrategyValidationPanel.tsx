

interface ValidationIssue {
  field: string;
  message: string;
}

interface StrategyValidationPanelProps {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export default function StrategyValidationPanel({ valid, errors, warnings }: StrategyValidationPanelProps) {
  if (valid && errors.length === 0 && warnings.length === 0) {
    return (
      <div className="bg-emerald-950/20 border border-emerald-900/40 text-emerald-400 text-xs rounded-xl p-3 flex items-center gap-2">
        <span className="text-sm">✓</span>
        <span>Strategy is validated and ready for backtesting.</span>
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {errors.length > 0 && (
        <div className="bg-rose-950/20 border border-rose-900/40 text-rose-400 text-xs rounded-xl p-3 space-y-1">
          <div className="font-extrabold flex items-center gap-1.5 text-rose-300">
            <span>🚨</span> Validation Errors ({errors.length})
          </div>
          <ul className="list-disc pl-4 space-y-1 mt-1 text-gray-300">
            {errors.map((err, idx) => (
              <li key={idx}>
                <span className="font-mono text-[10px] text-rose-400/80 mr-1">[{err.field}]</span>
                {err.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="bg-amber-950/20 border border-amber-900/40 text-amber-400 text-xs rounded-xl p-3 space-y-1">
          <div className="font-extrabold flex items-center gap-1.5 text-amber-300">
            <span>⚠️</span> Configuration Warnings ({warnings.length})
          </div>
          <ul className="list-disc pl-4 space-y-1 mt-1 text-gray-300">
            {warnings.map((warn, idx) => (
              <li key={idx}>
                <span className="font-mono text-[10px] text-amber-400/80 mr-1">[{warn.field}]</span>
                {warn.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
