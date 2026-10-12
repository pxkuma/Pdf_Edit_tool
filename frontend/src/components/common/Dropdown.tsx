import { useEffect, useRef, useState, type ReactNode } from "react";

interface DropdownProps {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
}

export function Dropdown({ trigger, children, align = "left" }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div className="menu" style={{ top: "calc(100% + 6px)", [align]: 0 }}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

interface MenuItemProps {
  icon?: ReactNode;
  label: string;
  hint?: string;
  danger?: boolean;
  onClick: () => void;
}

export function MenuItem({ icon, label, hint, danger, onClick }: MenuItemProps) {
  return (
    <button className="menu-item" onClick={onClick} style={danger ? { color: "var(--danger)" } : undefined}>
      {icon}
      <span>{label}</span>
      {hint && <span className="hint">{hint}</span>}
    </button>
  );
}
