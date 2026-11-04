/** The shape of each message type (§15.2). Shape and colour together, never colour alone. */
import { PERFORMATIVE_COLOR } from "@/lib/vocabulary";

const SHAPES: Record<string, (color: string) => React.ReactNode> = {
  INFORM: (color) => <circle r={4.5} fill={color} />,
  REQUEST: (color) => <rect x={-4} y={-4} width={8} height={8} fill={color} transform="rotate(45)" />,
  CHALLENGE: (color) => <polygon points="0,-6 5.5,4 -5.5,4" fill={color} />,
  REBUT: (color) => (
    <polyline points="-3,-5 3,0 -3,5" fill="none" stroke={color} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
  ),
  REVISE: (color) => <rect x={-4.5} y={-4.5} width={9} height={9} rx={1.5} fill={color} />,
  CONCEDE: (color) => <circle r={4.2} fill="none" stroke={color} strokeWidth={1.8} />,
  RESOLVE: (color) => (
    <>
      <circle r={5.4} fill="none" stroke={color} strokeWidth={1.5} />
      <circle r={1.6} fill={color} />
    </>
  ),
  VETO: (color) => (
    <path d="M-5 -5 L5 5 M5 -5 L-5 5" stroke={color} strokeWidth={2.8} strokeLinecap="round" />
  ),
  APPROVE: (color) => (
    <polyline points="-5,0 -1.5,4 5,-4.5" fill="none" stroke={color} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
  ),
};

/** For use inside an SVG, centred on the origin. */
export function GlyphShape({ performative }: { performative: string }) {
  const color = PERFORMATIVE_COLOR[performative] ?? "var(--color-text-3)";
  const shape = SHAPES[performative] ?? SHAPES.INFORM;
  return <>{shape?.(color)}</>;
}

/** For use in running text. */
export function Glyph({ performative, size = 14 }: { performative: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="-8 -8 16 16"
      aria-hidden
      className="inline-block shrink-0 align-[-2px]"
    >
      <GlyphShape performative={performative} />
    </svg>
  );
}
