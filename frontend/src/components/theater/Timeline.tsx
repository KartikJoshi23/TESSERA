"use client";

import {
  ChevronRight,
  Check,
  Pause,
  Play,
  Presentation,
  Radio,
  SkipBack,
  SkipForward,
  StepBack,
  StepForward,
  TriangleAlert,
  X,
} from "lucide-react";
import { useMemo } from "react";
import type { CaseEvent } from "@/lib/events";
import type { Playback } from "@/lib/hooks";
import { type MarkKind, nextMark, timelineOf } from "@/lib/timeline";
import { PHASE_LABEL } from "@/lib/vocabulary";

const SPEEDS = [0.5, 1, 2, 4];

const MARK_ICON: Record<MarkKind, React.ReactNode> = {
  conflict: <TriangleAlert size={13} color="var(--color-challenge)" aria-label="conflict" />,
  veto: <X size={14} color="var(--color-veto)" strokeWidth={3} aria-label="veto" />,
  approve: <Check size={14} color="var(--color-approve)" strokeWidth={3} aria-label="approved" />,
};

interface Props {
  events: CaseEvent[];
  playback: Playback;
  live: boolean;
  presenter: boolean;
  onPresenter: () => void;
}

export function Timeline({ events, playback, live, presenter, onPresenter }: Props) {
  const { position, playing, speed, following, seek, toggle, follow, setSpeed } = playback;
  const { rounds, marks } = useMemo(() => timelineOf(events), [events]);
  const current = rounds.findLastIndex((round) => round.start < position);
  const next = nextMark(marks, position);
  const phase = rounds[current]?.phase;

  return (
    <section className="glass flex flex-col gap-2 px-4 py-3" aria-label="Timeline" data-testid="timeline">
      <ol className="flex gap-1 overflow-x-auto">
        {rounds.map((round, index) => {
          const done = Math.min(Math.max((position - round.start) / (round.count || 1), 0), 1);
          return (
            <li
              key={`${round.phase}-${round.start}`}
              className="min-w-0"
              style={{ flex: `${Math.sqrt(round.count)} 1 4.75rem` }}
            >
              <button
                type="button"
                onClick={() => seek(round.start + 1)}
                aria-current={index === current ? "step" : undefined}
                className="group flex w-full min-w-0 cursor-pointer flex-col gap-1 rounded-md px-1 py-1 text-left hover:bg-white/5"
              >
                <span className="flex h-4 items-center gap-1 text-[11px] whitespace-nowrap">
                  <span
                    className={index === current ? "font-medium text-text" : "text-text-3"}
                  >
                    {PHASE_LABEL[round.phase] ?? round.phase}
                  </span>
                  {round.mark && MARK_ICON[round.mark]}
                </span>
                <span className="block h-1 overflow-hidden rounded-full bg-white/10">
                  <span
                    className="block h-full rounded-full bg-text-2"
                    style={{ width: `${done * 100}%` }}
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <input
        className="scrubber"
        type="range"
        min={0}
        max={events.length}
        value={position}
        onChange={(event) => seek(Number(event.target.value))}
        aria-label="Position in the case"
        aria-valuetext={`Event ${position} of ${events.length}${phase ? `, ${PHASE_LABEL[phase] ?? phase}` : ""}`}
      />

      <div className="flex flex-wrap items-center gap-1">
        <button type="button" className="icon-button" aria-label="Back to the start" onClick={() => seek(0)}>
          <SkipBack size={17} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="One event back"
          disabled={position === 0}
          onClick={() => seek(position - 1)}
        >
          <StepBack size={17} />
        </button>
        <button
          type="button"
          className="icon-button text-text"
          aria-label={playing ? "Pause" : "Play"}
          onClick={toggle}
        >
          {playing ? <Pause size={19} /> : <Play size={19} />}
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="One event forward"
          disabled={position >= events.length}
          onClick={() => seek(position + 1)}
        >
          <StepForward size={17} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="To the end"
          onClick={() => seek(events.length)}
        >
          <SkipForward size={17} />
        </button>

        <div className="mx-2 flex items-center gap-0.5" role="group" aria-label="Replay speed">
          {SPEEDS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={speed === value}
              onClick={() => setSpeed(value)}
              className={`data h-7 cursor-pointer rounded-md px-2 text-xs ${
                speed === value ? "bg-white/15 text-text" : "text-text-3 hover:text-text"
              }`}
            >
              {value}×
            </button>
          ))}
        </div>

        <button
          type="button"
          className="button h-8! px-3! text-xs!"
          disabled={!next}
          onClick={() => next && seek(next.index)}
        >
          Next {next ? (next.kind === "veto" ? "veto" : "conflict") : "conflict or veto"}
          <ChevronRight size={14} aria-hidden />
        </button>

        <div className="ml-auto flex items-center gap-3">
          {live && (
            <button
              type="button"
              onClick={follow}
              disabled={following}
              className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-inform disabled:cursor-default"
            >
              <Radio size={14} className={following ? "tile-breathe" : ""} aria-hidden />
              {following ? "Live" : "Back to live"}
            </button>
          )}
          <span className="data text-xs text-text-3">
            {position}/{events.length}
          </span>
          <button
            type="button"
            className="icon-button"
            aria-label="Presenter mode"
            aria-pressed={presenter}
            onClick={onPresenter}
          >
            <Presentation size={17} />
          </button>
        </div>
      </div>
    </section>
  );
}
