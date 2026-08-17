import React from "react";

const round4 = (value) => Math.max(0, Math.round((Number(value || 0) + Number.EPSILON) * 10000) / 10000);

export default function PoQtyMath({ value = 0, disabled = false, onChange, title = "PO Qty" }) {
  const apply = (operator) => {
    if (disabled) return;
    const current = Number(value || 0);
    const raw = window.prompt(`${title}: ${current} ${operator} berapa?`, operator === "×" || operator === "÷" ? "2" : "1");
    if (raw == null) return;
    const operand = Number(String(raw).replace(",", "."));
    if (!Number.isFinite(operand)) {
      window.alert("Angka tidak valid.");
      return;
    }
    if (operator === "÷" && operand === 0) {
      window.alert("Tidak bisa dibagi 0.");
      return;
    }
    let next = current;
    if (operator === "+") next = current + operand;
    if (operator === "−") next = current - operand;
    if (operator === "×") next = current * operand;
    if (operator === "÷") next = current / operand;
    onChange?.(round4(next));
  };

  return (
    <div className="ops-qty-math">
      <input
        className="ops-qty-input"
        type="number"
        min="0"
        step="0.0001"
        value={value ?? 0}
        disabled={disabled}
        onChange={(event) => onChange?.(round4(Number(event.target.value || 0)))}
      />
      <div className="ops-qty-math-buttons" aria-label={`Kalkulator ${title}`}>
        {["−", "+", "÷", "×"].map((operator) => (
          <button key={operator} type="button" disabled={disabled} onClick={() => apply(operator)} title={`${title} ${operator} angka`}>
            {operator}
          </button>
        ))}
      </div>
    </div>
  );
}
