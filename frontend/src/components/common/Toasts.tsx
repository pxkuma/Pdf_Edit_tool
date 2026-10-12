import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useEditor } from "../../store/editor";

const ICONS = {
  info: <Info size={18} color="var(--accent)" />,
  success: <CheckCircle2 size={18} color="var(--success)" />,
  warning: <AlertTriangle size={18} color="var(--warning)" />,
  error: <XCircle size={18} color="var(--danger)" />,
};

export function Toasts() {
  const toasts = useEditor((s) => s.toasts);
  const dismiss = useEditor((s) => s.dismissToast);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.kind}`}>
          {ICONS[toast.kind]}
          <p>{toast.message}</p>
          <button className="icon-btn small" onClick={() => dismiss(toast.id)} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
