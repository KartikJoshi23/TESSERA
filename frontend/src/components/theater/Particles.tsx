"use client";

import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Message } from "@/lib/reducer";
import { anchorOf, arcPoints, distance, type Point } from "./geometry";
import { GlyphShape } from "./Glyph";

const MAX_PARTICLES = 14;
/** Past this many at once the person has jumped, and a burst of light would explain nothing. */
const MAX_NEW_AT_ONCE = 8;
const SPEED = 340;

interface Particle {
  key: string;
  message: Message;
  from: Point;
  to: Point;
}

function toParticles(message: Message): Particle[] {
  const from = anchorOf(message.sender);
  return message.recipients.flatMap((recipient) => {
    const to = anchorOf(recipient);
    if (distance(from, to) < 1) return [];
    return [{ key: `${message.id}-${recipient}`, message, from, to }];
  });
}

/** One flight for every message the case has just reached. Going backwards shows none. */
export function useParticles(messages: Message[], still: boolean) {
  const [flying, setFlying] = useState<Particle[]>([]);
  const seen = useRef(messages.length);
  useEffect(() => {
    const fresh = messages.slice(seen.current);
    const backwards = messages.length < seen.current;
    seen.current = messages.length;
    if (backwards) setFlying([]);
    if (still || backwards || fresh.length === 0 || fresh.length > MAX_NEW_AT_ONCE) return;
    setFlying((current) => [...current, ...fresh.flatMap(toParticles)].slice(-MAX_PARTICLES));
  }, [messages, still]);
  const land = (key: string) => setFlying((current) => current.filter((p) => p.key !== key));
  return { flying, land };
}

interface FlightProps {
  particle: Particle;
  speed: number;
  onLand: (key: string) => void;
  onSelect: (id: string) => void;
}

function Flight({ particle, speed, onLand, onSelect }: FlightProps) {
  const { from, to, message } = particle;
  const points = useMemo(() => arcPoints(from, to), [from, to]);
  const seconds = Math.min(Math.max(distance(from, to) / SPEED, 0.55), 1.5) / speed;
  return (
    <motion.g
      className="cursor-pointer"
      initial={{ x: from.x, y: from.y, opacity: 0, scale: 1.5 }}
      animate={{
        x: points.map((point) => point.x),
        y: points.map((point) => point.y),
        opacity: [0, 1, 1, 1, 0.9],
        scale: 1.5,
      }}
      transition={{ duration: seconds, ease: "easeInOut" }}
      onAnimationComplete={() => onLand(particle.key)}
      onClick={() => onSelect(message.id)}
    >
      <title>{`${message.performative}: ${message.sender} to ${message.recipients.join(", ")}`}</title>
      <circle r={10} fill="transparent" />
      <GlyphShape performative={message.performative} />
    </motion.g>
  );
}

interface Props {
  flying: Particle[];
  speed: number;
  glow: string;
  onLand: (key: string) => void;
  onSelect: (id: string) => void;
}

export function Particles({ flying, speed, glow, onLand, onSelect }: Props) {
  return (
    <g filter={`url(#${glow})`}>
      {flying.map((particle) => (
        <Flight
          key={particle.key}
          particle={particle}
          speed={speed}
          onLand={onLand}
          onSelect={onSelect}
        />
      ))}
    </g>
  );
}
