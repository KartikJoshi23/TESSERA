/**
 * Text as the models saw it. Restricted values were replaced by placeholders before any model call,
 * and they are shown here as chips, so the masking can be seen working.
 */
const PLACEHOLDER = /(⟦[^⟧]+⟧)/;

export function Masked({ text }: { text: string }) {
  return (
    <>
      {text.split(PLACEHOLDER).map((part, index) =>
        PLACEHOLDER.test(part) ? (
          <span
            // The split gives each part a fixed place in this text.
            key={index}
            title="Masked: no model ever saw this value"
            className="data mx-0.5 rounded border border-dfsa/40 bg-dfsa/10 px-1 py-px text-[0.85em] text-dfsa"
          >
            {part.slice(1, -1).replace(/^[A-Z]:/, "")}
          </span>
        ) : (
          part
        ),
      )}
    </>
  );
}
