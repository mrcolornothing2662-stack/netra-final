import React from "react";
import { Icon } from "../icons";
import { useTheme } from "../../state/useTheme";

interface ThemeToggleProps {
  className?: string;
  showLabel?: boolean;
}

export function ThemeToggle({ className, showLabel = false }: ThemeToggleProps) {
  const { theme, toggleTheme, isLight } = useTheme();

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "6px",
        height: "32px",
        padding: showLabel ? "0 10px" : "0 8px",
        borderRadius: "var(--radius-button)",
        border: "1px solid var(--line)",
        background: "var(--surface-1)",
        color: "var(--text-primary)",
        cursor: "pointer",
        fontSize: "12px",
        fontFamily: "var(--font-sans)",
        transition: "all var(--dur-2) var(--ease-out)",
        boxShadow: "var(--shadow-1)",
      }}
      title={isLight ? "Switch to dark theme" : "Switch to light theme"}
      aria-label={isLight ? "Switch to dark theme" : "Switch to light theme"}
    >
      <Icon
        name={isLight ? "moon" : "sun"}
        size={15}
        style={{
          color: isLight ? "var(--accent)" : "var(--warning)",
          transition: "transform 0.2s ease",
        }}
      />
      {showLabel && (
        <span style={{ fontWeight: 500, fontSize: "11px", letterSpacing: "0.02em" }}>
          {isLight ? "Dark" : "Light"}
        </span>
      )}
    </button>
  );
}
